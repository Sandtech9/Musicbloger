import os
import sqlite3
import hashlib
import secrets
import time
import json
import shutil
import urllib.request
import urllib.parse
from typing import Optional, List, Dict, Any, Tuple

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
ORIGINAL_DB_FILE = os.path.join(BASE_DIR, "zedhits.db")
SCHEMA_FILE = os.path.join(BASE_DIR, "schema.sql")

BLOB_DB_FILENAME = "zedhits_cloud_db.db"
_LAST_DB_DOWNLOAD_TIME = 0.0

def get_vercel_blob_token() -> str:
    return (
        os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip() or
        os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN", "").strip() or
        os.environ.get("VERCEL_OIDC_TOKEN", "").strip()
    )

def download_db_from_vercel_blob(target_path: str, force: bool = False) -> bool:
    global _LAST_DB_DOWNLOAD_TIME
    token = get_vercel_blob_token()
    if not token:
        return False

    now = time.time()
    if not force and os.path.exists(target_path) and (now - _LAST_DB_DOWNLOAD_TIME < 10):
        return True

    try:
        req = urllib.request.Request(
            f"https://blob.vercel-storage.com/?prefix={BLOB_DB_FILENAME}",
            headers={"Authorization": f"Bearer {token}", "x-api-version": "7"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                blobs = data.get("blobs", [])
                matching = [b for b in blobs if b.get("pathname") == BLOB_DB_FILENAME or BLOB_DB_FILENAME in b.get("url", "")]
                if matching:
                    matching.sort(key=lambda x: x.get("uploadedAt", ""), reverse=True)
                    download_url = matching[0]["url"]
                    dl_req = urllib.request.Request(download_url)
                    with urllib.request.urlopen(dl_req, timeout=15) as dl_resp:
                        if dl_resp.status == 200:
                            content = dl_resp.read()
                            if len(content) > 1000:
                                with open(target_path, "wb") as f:
                                    f.write(content)
                                _LAST_DB_DOWNLOAD_TIME = time.time()
                                print(f"[Cloud DB Sync] [OK] Downloaded latest DB snapshot from Vercel Blob ({len(content)} bytes)")
                                return True
    except Exception as e:
        print(f"[Cloud DB Sync] [NOTICE] Blob snapshot check: {e}")
    return False

def sync_db_to_vercel_blob(db_path: str) -> bool:
    token = get_vercel_blob_token()
    if not token or not os.path.exists(db_path):
        return False
    try:
        with open(db_path, "rb") as f:
            file_bytes = f.read()

        if len(file_bytes) < 1000:
            return False

        url = f"https://blob.vercel-storage.com/{BLOB_DB_FILENAME}?access=public"
        headers = {
            "Authorization": f"Bearer {token}",
            "x-api-version": "7",
            "x-content-type": "application/x-sqlite3",
            "x-add-random-suffix": "0"
        }
        req = urllib.request.Request(url, data=file_bytes, headers=headers, method="PUT")
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print(f"[Cloud DB Sync] [OK] Successfully uploaded SQLite snapshot to Vercel Blob ({len(file_bytes)} bytes)")
                return True
    except Exception as e:
        print(f"[Cloud DB Sync] [WARN] Upload DB to Vercel Blob failed: {e}")
    return False

def get_db_path() -> str:
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        tmp_db = os.path.join("/tmp", "zedhits.db")
        if not os.path.exists(tmp_db):
            downloaded = download_db_from_vercel_blob(tmp_db, force=True)
            if not downloaded and os.path.exists(ORIGINAL_DB_FILE):
                try:
                    shutil.copy2(ORIGINAL_DB_FILE, tmp_db)
                except Exception:
                    pass
        return tmp_db
    return ORIGINAL_DB_FILE

class AutoSyncConnection(sqlite3.Connection):
    def commit(self):
        super().commit()
        if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or get_vercel_blob_token():
            try:
                sync_db_to_vercel_blob(get_db_path())
            except Exception as e:
                print(f"[AutoSyncConnection] [NOTICE] {e}")

def get_connection() -> sqlite3.Connection:
    """Creates a thread-safe connection with PRAGMA foreign_keys enforced and Vercel cloud sync."""
    target_db = get_db_path()
    conn = sqlite3.connect(target_db, timeout=30.0, check_same_thread=False, factory=AutoSyncConnection)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except Exception:
        pass
    return conn



# ----------------------------------------------------------------------------
# PBKDF2 Password Utilities (100,000 Iterations)
# ----------------------------------------------------------------------------
def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return key.hex(), salt

def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, expected_hash)

# ----------------------------------------------------------------------------
# Database Initializer & Migration
# ----------------------------------------------------------------------------
def init_db():
    conn = get_connection()
    try:
        with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()

        # Dynamic Schema Migration (Safe column additions)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(tracks)")
        columns = [row["name"] for row in cursor.fetchall()]
        
        if "cover_url" not in columns:
            conn.execute("ALTER TABLE tracks ADD COLUMN cover_url TEXT DEFAULT ''")
        if "bitrate_kbps" not in columns:
            conn.execute("ALTER TABLE tracks ADD COLUMN bitrate_kbps INTEGER DEFAULT 320")
        if "album_name" not in columns:
            conn.execute("ALTER TABLE tracks ADD COLUMN album_name TEXT DEFAULT ''")
        if "featured_artists" not in columns:
            conn.execute("ALTER TABLE tracks ADD COLUMN featured_artists TEXT DEFAULT ''")
        if "downloads_count" not in columns:
            conn.execute("ALTER TABLE tracks ADD COLUMN downloads_count INTEGER DEFAULT 0")
        if "lyrics" not in columns:
            conn.execute("ALTER TABLE tracks ADD COLUMN lyrics TEXT DEFAULT ''")

        cursor.execute("PRAGMA table_info(artists)")
        artist_cols = [row["name"] for row in cursor.fetchall()]
        if "slug" not in artist_cols:
            conn.execute("ALTER TABLE artists ADD COLUMN slug TEXT DEFAULT ''")
        if "cover_url" not in artist_cols:
            conn.execute("ALTER TABLE artists ADD COLUMN cover_url TEXT DEFAULT ''")

        cursor.execute("PRAGMA table_info(genres)")
        genre_cols = [row["name"] for row in cursor.fetchall()]
        if "slug" not in genre_cols:
            conn.execute("ALTER TABLE genres ADD COLUMN slug TEXT DEFAULT ''")

        # Ensure standard genres exist
        default_genres = [
            ('Afrobeats', 'afrobeats'),
            ('Dancehall', 'dancehall'),
            ('Gospel', 'gospel'),
            ('Kalindula', 'kalindula'),
            ('Zed Hip Hop', 'zed-hip-hop'),
            ('RnB', 'rnb'),
            ('Pop', 'pop'),
            ('Others', 'others')
        ]
        for g_name, g_slug in default_genres:
            conn.execute("INSERT OR IGNORE INTO genres (name, slug) VALUES (?, ?)", (g_name, g_slug))

        # Team Members Table Migration
        cursor.execute("PRAGMA table_info(team_members)")
        team_cols = [row["name"] for row in cursor.fetchall()]
        if "photo_path" not in team_cols and "photo_url" in team_cols:
            conn.execute("ALTER TABLE team_members ADD COLUMN photo_path TEXT DEFAULT '/media/team/default-avatar.png'")

        # Videos Table Creation
        conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE RESTRICT,
                genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
                youtube_url TEXT NOT NULL,
                thumbnail_url TEXT DEFAULT '',
                director TEXT DEFAULT '',
                duration_seconds INTEGER DEFAULT 0,
                views_count INTEGER DEFAULT 0,
                downloads_count INTEGER DEFAULT 0,
                is_featured BOOLEAN DEFAULT 0,
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_artist ON videos(artist_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC)")

        # Ensure default-avatar.png exists on disk
        team_dir = os.path.join(BASE_DIR, "media", "team")
        os.makedirs(team_dir, exist_ok=True)
        default_avatar_file = os.path.join(team_dir, "default-avatar.png")
        if not os.path.exists(default_avatar_file):
            import base64
            b = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAYAAABw4pVUAAAACXBIWXMAAAsTAAALEwEAmpwYAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAACvSURBVHgB7dAxEQAgEMDAAb5/Z6rBQvK3A1t21927Z5YgISFCSFCIEBIUIoQEhQghQSFCSFCIEBIUIoQEhQghQSFCSFCIEBIUIoQEhQghQSFCSFCIEBIUIoQEhQghQSFCSFCIEBIUIoQEhQghQSFCSFCIEBIUIoQEhQghQSFCSNgl2D/3b7qD44YAAAAASUVORK5CYII=')
            with open(default_avatar_file, "wb") as f:
                f.write(b)

        # Ensure admin_sessions table exists for serverless persistence
        conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Seed default admin if none exists
        cursor.execute("SELECT COUNT(*) as count FROM admins")
        if cursor.fetchone()["count"] == 0:
            pwd_hash, salt = hash_password("admin123")
            cursor.execute(
                "INSERT INTO admins (username, password_hash, salt) VALUES (?, ?, ?)",
                ("admin", pwd_hash, salt)
            )
            conn.commit()
            print("[Zedhits DB] [OK] Initialized and seeded default admin ('admin' / 'admin123').")
    finally:
        conn.close()

# ----------------------------------------------------------------------------
# Admin & Auth Queries
# ----------------------------------------------------------------------------
def get_admin_by_username(username: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM admins WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def save_admin_session(token: str, username: str):
    conn = get_connection()
    try:
        with conn:
            conn.execute("INSERT OR REPLACE INTO admin_sessions (token, username) VALUES (?, ?)", (token, username))
    except Exception:
        pass
    finally:
        conn.close()

def verify_admin_session(token: str) -> Optional[str]:
    if not token or len(token) < 16:
        return None
    conn = get_connection()
    try:
        row = conn.execute("SELECT username FROM admin_sessions WHERE token = ?", (token,)).fetchone()
        return row["username"] if row else None
    except Exception:
        return None
    finally:
        conn.close()

def delete_admin_session(token: str):
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
    except Exception:
        pass
    finally:
        conn.close()

def update_admin_credentials(current_username: str, new_username: str, new_password: Optional[str] = None) -> bool:
    conn = get_connection()
    try:
        admin = conn.execute(
            "SELECT * FROM admins WHERE username = ? COLLATE NOCASE", (current_username,)
        ).fetchone()
        if not admin:
            return False

        with conn:
            if new_password:
                pwd_hash, salt = hash_password(new_password)
                conn.execute(
                    "UPDATE admins SET username = ?, password_hash = ?, salt = ? WHERE id = ?",
                    (new_username.strip(), pwd_hash, salt, admin["id"])
                )
            else:
                conn.execute(
                    "UPDATE admins SET username = ? WHERE id = ?",
                    (new_username.strip(), admin["id"])
                )
        return True
    finally:
        conn.close()

def update_admin_last_login(admin_id: int):
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE admins SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (admin_id,)
            )
    except Exception:
        pass
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Site Settings (Dynamic CMS)
# ----------------------------------------------------------------------------
def get_site_settings() -> Dict[str, str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT key, value FROM site_settings").fetchall()
        settings = {row["key"]: row["value"] for row in rows}
        defaults = {
            # 1. Brand & Identity
            "site_title": "ZedHits",
            "nav_logo_text": "ZedHits",
            "tagline": "Download The Latest Zambian Music In 2026",
            "hero_title": "Download The Latest Zambian Music In 2026",
            "hero_subtitle": "The Pulse of Zambian & African Music Streaming & Studio Master MP3 Downloads",
            "favicon_url": "",
            "logo_url": "",
            "footer_text": "© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.",

            # 2. Theme & Appearance
            "accent_color": "#06801e",
            "bg_base_color": "#f7f8f8",
            "card_surface_color": "#ffffff",
            "text_primary_color": "#2c2f34",

            # 3. Banner & Announcements
            "banner_active": "true",
            "banner_message": "Are you an Artist or Producer? Get your song uploaded & promoted on ZedHits!",
            "banner_type": "promotional",
            "banner_btn_text": "Chat WhatsApp",
            "banner_btn_link": "",

            # 4. Feature & Content Controls
            "allow_downloads": "true",
            "show_play_counts": "true",
            "show_release_dates": "true",
            "stream_quality_label": "320k HD",
            "default_sort_mode": "latest",
            "empty_state_msg": "No Songs Found in this Selection. Select another genre or explore the latest releases.",
            "section_latest_title": "The Latest",
            "section_trending_title": "TRENDING",
            "section_artists_title": "ARTISTS",

            # 5. Contact & Social Links
            "contact_whatsapp": "+260970000000",
            "contact_phone": "+260970000000",
            "contact_whatsapp_msg": "Hello ZedHits, I want to submit my song for upload and promotion.",
            "social_facebook": "https://facebook.com",
            "social_twitter": "https://x.com",
            "social_instagram": "https://instagram.com",
            "social_youtube": "https://youtube.com",
            "contact_email": "support@zedhits.com",

            # 6. About Us
            "about_title": "About ZedHits",
            "about_description": "ZedHits is Zambia's premier autonomous music streaming and digital audio distribution platform. Founded with a vision to empower Zambian and African artists, ZedHits bridges the gap between creative talent and global music enthusiasts with studio-master quality audio, instant discography archives, and high-speed distribution.",
            "about_mission": "Empowering African musical heritage through state-of-the-art streaming infrastructure and direct artist-to-fan discovery.",
            "about_stats_artists": "500+",
            "about_stats_streams": "1.2M+",
            "about_stats_quality": "320 kbps HD"
        }
        for k, v in defaults.items():
            if k not in settings:
                settings[k] = v
        return settings
    finally:
        conn.close()

def update_site_settings(settings_dict: Dict[str, str]) -> Dict[str, str]:
    conn = get_connection()
    try:
        with conn:
            for k, v in settings_dict.items():
                conn.execute(
                    """
                    INSERT INTO site_settings (key, value) 
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (k, str(v))
                )
        return get_site_settings()
    finally:
        conn.close()

# ----------------------------------------------------------------------------
# Artists & Genres Helpers
# ----------------------------------------------------------------------------
def get_or_create_artist(conn: sqlite3.Connection, name: str) -> int:
    name_clean = name.strip()
    slug = name_clean.lower().replace(" ", "-").replace("/", "-")
    row = conn.execute("SELECT id FROM artists WHERE name = ? COLLATE NOCASE", (name_clean,)).fetchone()
    if row:
        return row["id"]
    
    cursor = conn.execute(
        "INSERT INTO artists (name, slug) VALUES (?, ?)",
        (name_clean, slug)
    )
    return cursor.lastrowid

def get_or_create_genre(conn: sqlite3.Connection, name: str) -> int:
    name_clean = name.strip()
    slug = name_clean.lower().replace(" ", "-").replace("/", "-")
    row = conn.execute("SELECT id FROM genres WHERE name = ? COLLATE NOCASE", (name_clean,)).fetchone()
    if row:
        return row["id"]
    
    cursor = conn.execute(
        "INSERT INTO genres (name, slug) VALUES (?, ?)",
        (name_clean, slug)
    )
    return cursor.lastrowid

def get_genres() -> List[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name, slug FROM genres ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def format_stream_url(storage_path: str) -> str:
    if not storage_path:
        return ""
    if storage_path.startswith("http://") or storage_path.startswith("https://"):
        return storage_path
    return f"/media/tracks/{os.path.basename(storage_path)}"

def get_artist_profile(artist_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        artist_row = conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not artist_row:
            return None
        
        artist = dict(artist_row)
        tracks_query = """
            SELECT 
                t.id, 
                t.title, 
                t.featured_artists,
                t.album_name,
                t.lyrics,
                t.duration_seconds, 
                t.bitrate_kbps,
                t.cover_url,
                t.plays_count, 
                t.downloads_count,
                t.created_at,
                g.id as genre_id, 
                g.name as genre,
                mf.storage_path,
                mf.file_size_bytes,
                mf.sha256_hash
            FROM tracks t
            JOIN genres g ON t.genre_id = g.id
            JOIN media_files mf ON mf.track_id = t.id
            WHERE t.artist_id = ?
            ORDER BY t.plays_count DESC, t.created_at DESC
        """
        track_rows = conn.execute(tracks_query, (artist_id,)).fetchall()
        tracks = []
        total_plays = 0
        total_downloads = 0

        for r in track_rows:
            d = dict(r)
            d["artist"] = artist["name"]
            d["artist_id"] = artist["id"]
            d["stream_url"] = format_stream_url(d.get("storage_path", ""))
            total_plays += d.get("plays_count", 0)
            total_downloads += d.get("downloads_count", 0)
            tracks.append(d)

        artist["tracks"] = tracks
        artist["total_tracks"] = len(tracks)
        artist["total_plays"] = total_plays
        artist["total_downloads"] = total_downloads
        artist["cover_url"] = tracks[0]["cover_url"] if tracks and tracks[0]["cover_url"] else ""
        return artist
    finally:
        conn.close()

def get_trending_artists(limit: int = 8) -> List[dict]:
    conn = get_connection()
    try:
        query = """
            SELECT 
                a.id, 
                a.name, 
                a.slug,
                COUNT(t.id) as track_count,
                COALESCE(SUM(t.plays_count), 0) as total_plays,
                (SELECT t2.cover_url FROM tracks t2 WHERE t2.artist_id = a.id AND t2.cover_url != '' LIMIT 1) as cover_url
            FROM artists a
            JOIN tracks t ON t.artist_id = a.id
            GROUP BY a.id
            ORDER BY total_plays DESC, track_count DESC
            LIMIT ?
        """
        rows = conn.execute(query, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_artists(only_with_tracks: bool = False) -> List[dict]:
    conn = get_connection()
    try:
        having_clause = "HAVING track_count > 0" if only_with_tracks else ""
        query = f"""
            SELECT 
                a.id, 
                a.name, 
                a.slug,
                a.bio,
                COALESCE(NULLIF(a.cover_url, ''), (SELECT t2.cover_url FROM tracks t2 WHERE t2.artist_id = a.id AND t2.cover_url != '' LIMIT 1), '') as cover_url,
                COUNT(t.id) as track_count,
                COALESCE(SUM(t.plays_count), 0) as total_plays,
                COALESCE(SUM(t.downloads_count), 0) as total_downloads
            FROM artists a
            LEFT JOIN tracks t ON t.artist_id = a.id
            GROUP BY a.id
            {having_clause}
            ORDER BY track_count DESC, total_plays DESC, a.name ASC
        """
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_artist_by_id(artist_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def create_artist(name: str, bio: str = "", cover_url: str = "") -> dict:
    conn = get_connection()
    try:
        with conn:
            name_clean = name.strip()
            slug = name_clean.lower().replace(" ", "-").replace("/", "-")
            cursor = conn.execute(
                "INSERT INTO artists (name, slug, bio, cover_url) VALUES (?, ?, ?, ?)",
                (name_clean, slug, bio.strip(), cover_url.strip())
            )
            artist_id = cursor.lastrowid
        return get_artist_profile(artist_id)
    finally:
        conn.close()

def update_artist(
    artist_id: int, 
    name: Optional[str] = None, 
    bio: Optional[str] = None, 
    cover_url: Optional[str] = None
) -> Optional[dict]:
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        if not existing:
            return None

        with conn:
            if name is not None and len(name.strip()) > 0:
                name_clean = name.strip()
                slug = name_clean.lower().replace(" ", "-").replace("/", "-")
                conn.execute("UPDATE artists SET name = ?, slug = ? WHERE id = ?", (name_clean, slug, artist_id))
            if bio is not None:
                conn.execute("UPDATE artists SET bio = ? WHERE id = ?", (bio.strip(), artist_id))
            if cover_url is not None:
                conn.execute("UPDATE artists SET cover_url = ? WHERE id = ?", (cover_url.strip(), artist_id))

        return get_artist_profile(artist_id)
    finally:
        conn.close()

def delete_artist(artist_id: int) -> bool:
    conn = get_connection()
    try:
        track_count = conn.execute("SELECT COUNT(*) as c FROM tracks WHERE artist_id = ?", (artist_id,)).fetchone()["c"]
        if track_count > 0:
            return False  # Cannot delete artist with active tracks

        with conn:
            conn.execute("DELETE FROM artists WHERE id = ?", (artist_id,))
        return True
    finally:
        conn.close()

def purge_empty_artists() -> int:
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("""
                DELETE FROM artists 
                WHERE id NOT IN (SELECT DISTINCT artist_id FROM tracks)
            """)
            return cursor.rowcount
    finally:
        conn.close()


# ----------------------------------------------------------------------------
# Tracks & Media Files CRUD
# ----------------------------------------------------------------------------
def get_tracks(
    search: Optional[str] = None,
    genre_id: Optional[int] = None,
    sort_by: str = "latest",
    limit: Optional[int] = None
) -> List[dict]:
    conn = get_connection()
    try:
        query = """
            SELECT 
                t.id, 
                t.title, 
                t.featured_artists,
                t.album_name,
                t.lyrics,
                t.duration_seconds, 
                t.bitrate_kbps,
                t.cover_url,
                t.plays_count, 
                t.downloads_count,
                t.created_at,
                a.id as artist_id, 
                a.name as artist,
                g.id as genre_id, 
                g.name as genre,
                mf.file_name,
                mf.storage_path,
                mf.file_size_bytes,
                mf.mime_type,
                mf.sha256_hash
            FROM tracks t
            JOIN artists a ON t.artist_id = a.id
            JOIN genres g ON t.genre_id = g.id
            JOIN media_files mf ON mf.track_id = t.id
            WHERE 1=1
        """
        params = []
        if search:
            query += " AND (t.title LIKE ? OR a.name LIKE ? OR g.name LIKE ? OR t.album_name LIKE ? OR t.featured_artists LIKE ?)"
            term = f"%{search.strip()}%"
            params.extend([term, term, term, term, term])
        if genre_id:
            query += " AND t.genre_id = ?"
            params.append(genre_id)

        if sort_by == "plays" or sort_by == "top":
            query += " ORDER BY t.plays_count DESC, t.id DESC"
        elif sort_by == "downloads":
            query += " ORDER BY t.downloads_count DESC, t.id DESC"
        elif sort_by == "trending":
            query += " ORDER BY (t.plays_count * 2 + t.downloads_count * 3) DESC, t.created_at DESC"
        else:
            query += " ORDER BY t.created_at DESC, t.id DESC"

        if limit:
            query += f" LIMIT {int(limit)}"

        rows = conn.execute(query, params).fetchall()
        tracks = []
        for r in rows:
            d = dict(r)
            d["stream_url"] = format_stream_url(d.get("storage_path", ""))
            if not d.get("cover_url"):
                d["cover_url"] = ""
            tracks.append(d)
        return tracks
    finally:
        conn.close()

def get_track_by_id(track_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT 
                t.id, 
                t.title, 
                t.featured_artists,
                t.album_name,
                t.lyrics,
                t.duration_seconds, 
                t.bitrate_kbps,
                t.cover_url,
                t.plays_count, 
                t.downloads_count,
                t.created_at,
                a.id as artist_id, 
                a.name as artist,
                g.id as genre_id, 
                g.name as genre,
                mf.file_name,
                mf.storage_path,
                mf.file_size_bytes,
                mf.mime_type,
                mf.sha256_hash
            FROM tracks t
            JOIN artists a ON t.artist_id = a.id
            JOIN genres g ON t.genre_id = g.id
            JOIN media_files mf ON mf.track_id = t.id
            WHERE t.id = ?
            """,
            (track_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stream_url"] = format_stream_url(d.get("storage_path", ""))
        if not d.get("cover_url"):
            d["cover_url"] = ""
        return d
    finally:
        conn.close()

def get_related_tracks(track_id: int, limit: int = 4) -> List[dict]:
    track = get_track_by_id(track_id)
    if not track:
        return []
    
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT 
                t.id, 
                t.title, 
                t.featured_artists,
                t.album_name,
                t.duration_seconds, 
                t.bitrate_kbps,
                t.cover_url,
                t.plays_count, 
                t.downloads_count,
                t.created_at,
                a.id as artist_id, 
                a.name as artist,
                g.id as genre_id, 
                g.name as genre,
                mf.storage_path
            FROM tracks t
            JOIN artists a ON t.artist_id = a.id
            JOIN genres g ON t.genre_id = g.id
            JOIN media_files mf ON mf.track_id = t.id
            WHERE t.id != ? AND (t.artist_id = ? OR t.genre_id = ?)
            ORDER BY t.plays_count DESC
            LIMIT ?
            """,
            (track_id, track["artist_id"], track["genre_id"], limit)
        ).fetchall()
        
        tracks = []
        for r in rows:
            d = dict(r)
            d["stream_url"] = format_stream_url(d.get("storage_path", ""))
            tracks.append(d)
        return tracks
    finally:
        conn.close()

def check_hash_exists(sha256_hash: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT t.id, t.title, a.name as artist, mf.storage_path 
            FROM media_files mf
            JOIN tracks t ON mf.track_id = t.id
            JOIN artists a ON t.artist_id = a.id
            WHERE mf.sha256_hash = ?
            """,
            (sha256_hash,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def get_track_by_filename(filename: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT t.id, t.title, mf.storage_path, mf.file_name 
            FROM media_files mf
            JOIN tracks t ON mf.track_id = t.id
            WHERE mf.storage_path LIKE ? OR mf.file_name = ?
            LIMIT 1
            """,
            (f"%{filename}", filename)
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None
    finally:
        conn.close()

def create_track(
    title: str,
    artist_name: str,
    genre_name: str,
    duration_seconds: int,
    file_name: str,
    storage_path: str,
    file_size_bytes: int,
    mime_type: str,
    sha256_hash: str,
    cover_url: str = "",
    bitrate_kbps: int = 320,
    album_name: str = "",
    lyrics: str = "",
    featured_artists: str = ""
) -> dict:
    conn = get_connection()
    try:
        with conn:
            artist_id = get_or_create_artist(conn, artist_name)
            genre_id = get_or_create_genre(conn, genre_name)

            cursor = conn.execute(
                """
                INSERT INTO tracks (title, artist_id, featured_artists, genre_id, album_name, lyrics, duration_seconds, bitrate_kbps, cover_url, plays_count, downloads_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
                """,
                (title.strip(), artist_id, featured_artists.strip(), genre_id, album_name.strip(), lyrics.strip(), duration_seconds, bitrate_kbps, cover_url.strip())
            )
            track_id = cursor.lastrowid

            conn.execute(
                """
                INSERT INTO media_files (track_id, file_name, storage_path, file_size_bytes, mime_type, sha256_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (track_id, file_name, storage_path, file_size_bytes, mime_type, sha256_hash)
            )

        return get_track_by_id(track_id)
    finally:
        conn.close()

def update_track(
    track_id: int,
    title: Optional[str] = None,
    artist_name: Optional[str] = None,
    genre_name: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    album_name: Optional[str] = None,
    lyrics: Optional[str] = None,
    bitrate_kbps: Optional[int] = None,
    cover_url: Optional[str] = None,
    featured_artists: Optional[str] = None
) -> Optional[dict]:
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if not existing:
            return None

        with conn:
            if artist_name:
                artist_id = get_or_create_artist(conn, artist_name)
                conn.execute("UPDATE tracks SET artist_id = ? WHERE id = ?", (artist_id, track_id))

            if genre_name:
                genre_id = get_or_create_genre(conn, genre_name)
                conn.execute("UPDATE tracks SET genre_id = ? WHERE id = ?", (genre_id, track_id))

            if title is not None:
                conn.execute("UPDATE tracks SET title = ? WHERE id = ?", (title.strip(), track_id))

            if featured_artists is not None:
                conn.execute("UPDATE tracks SET featured_artists = ? WHERE id = ?", (featured_artists.strip(), track_id))

            if album_name is not None:
                conn.execute("UPDATE tracks SET album_name = ? WHERE id = ?", (album_name.strip(), track_id))

            if lyrics is not None:
                conn.execute("UPDATE tracks SET lyrics = ? WHERE id = ?", (lyrics.strip(), track_id))

            if duration_seconds is not None:
                conn.execute("UPDATE tracks SET duration_seconds = ? WHERE id = ?", (duration_seconds, track_id))

            if bitrate_kbps is not None:
                conn.execute("UPDATE tracks SET bitrate_kbps = ? WHERE id = ?", (bitrate_kbps, track_id))

            if cover_url is not None:
                conn.execute("UPDATE tracks SET cover_url = ? WHERE id = ?", (cover_url.strip(), track_id))

        return get_track_by_id(track_id)
    finally:
        conn.close()

def delete_track(track_id: int) -> Optional[str]:
    conn = get_connection()
    try:
        media_row = conn.execute("SELECT storage_path FROM media_files WHERE track_id = ?", (track_id,)).fetchone()
        if not media_row:
            return None
        storage_path = media_row["storage_path"]

        with conn:
            # Foreign key ON DELETE CASCADE automatically removes media_files entry
            conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))

        return storage_path
    finally:
        conn.close()

def increment_plays(track_id: int) -> int:
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE tracks SET plays_count = plays_count + 1 WHERE id = ?", (track_id,))
            row = conn.execute("SELECT plays_count FROM tracks WHERE id = ?", (track_id,)).fetchone()
            return row["plays_count"] if row else 0
    finally:
        conn.close()

def increment_downloads(track_id: int) -> int:
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE tracks SET downloads_count = downloads_count + 1 WHERE id = ?", (track_id,))
            row = conn.execute("SELECT downloads_count FROM tracks WHERE id = ?", (track_id,)).fetchone()
            return row["downloads_count"] if row else 0
    finally:
        conn.close()

def get_analytics_summary() -> dict:
    conn = get_connection()
    try:
        total_tracks = conn.execute("SELECT COUNT(*) as c FROM tracks").fetchone()["c"]
        total_artists = conn.execute("SELECT COUNT(*) as c FROM artists").fetchone()["c"]
        total_plays = conn.execute("SELECT COALESCE(SUM(plays_count), 0) as s FROM tracks").fetchone()["s"]
        total_downloads = conn.execute("SELECT COALESCE(SUM(downloads_count), 0) as s FROM tracks").fetchone()["s"]
        total_bytes = conn.execute("SELECT COALESCE(SUM(file_size_bytes), 0) as s FROM media_files").fetchone()["s"]

        top_tracks = get_tracks(sort_by="plays", limit=5)
        
        top_artists_rows = conn.execute(
            """
            SELECT a.id, a.name, COUNT(t.id) as track_count, COALESCE(SUM(t.plays_count), 0) as total_plays
            FROM artists a
            JOIN tracks t ON t.artist_id = a.id
            GROUP BY a.id
            ORDER BY total_plays DESC
            LIMIT 5
            """
        ).fetchall()

        top_artists = [dict(r) for r in top_artists_rows]

        return {
            "total_tracks": total_tracks,
            "total_artists": total_artists,
            "total_plays": total_plays,
            "total_downloads": total_downloads,
            "total_storage_mb": round(total_bytes / (1024 * 1024), 2),
            "top_tracks": top_tracks,
            "top_artists": top_artists
        }
    finally:
        conn.close()

def get_daily_activity(days: int = 14) -> List[dict]:
    conn = get_connection()
    try:
        query = """
            SELECT date(created_at) as date, COUNT(id) as uploads_count
            FROM tracks
            GROUP BY date(created_at)
            ORDER BY date DESC
            LIMIT ?
        """
        rows = conn.execute(query, (days,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ----------------------------------------------------------------------------
# Team & About Us Profiles Module
# ----------------------------------------------------------------------------
def get_team_members() -> List[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM team_members ORDER BY display_order ASC, id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def get_team_member_by_id(member_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM team_members WHERE id = ?", (member_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def create_team_member(
    name: str, 
    role: str, 
    bio: str = "", 
    photo_path: str = "/media/team/default-avatar.png", 
    social_links: str = "{}", 
    display_order: int = 0
) -> dict:
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO team_members (name, role, bio, photo_path, social_links, display_order)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name.strip(), role.strip(), bio.strip(), photo_path.strip(), social_links, display_order)
            )
            member_id = cursor.lastrowid
        return get_team_member_by_id(member_id)
    finally:
        conn.close()

def update_team_member(
    member_id: int, 
    name: Optional[str] = None, 
    role: Optional[str] = None, 
    bio: Optional[str] = None, 
    photo_path: Optional[str] = None, 
    social_links: Optional[str] = None, 
    display_order: Optional[int] = None
) -> Optional[dict]:
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM team_members WHERE id = ?", (member_id,)).fetchone()
        if not existing:
            return None

        with conn:
            if name is not None:
                conn.execute("UPDATE team_members SET name = ? WHERE id = ?", (name.strip(), member_id))
            if role is not None:
                conn.execute("UPDATE team_members SET role = ? WHERE id = ?", (role.strip(), member_id))
            if bio is not None:
                conn.execute("UPDATE team_members SET bio = ? WHERE id = ?", (bio.strip(), member_id))
            if photo_path is not None:
                conn.execute("UPDATE team_members SET photo_path = ? WHERE id = ?", (photo_path.strip(), member_id))
            if social_links is not None:
                conn.execute("UPDATE team_members SET social_links = ? WHERE id = ?", (social_links, member_id))
            if display_order is not None:
                conn.execute("UPDATE team_members SET display_order = ? WHERE id = ?", (display_order, member_id))

        return get_team_member_by_id(member_id)
    finally:
        conn.close()

def delete_team_member(member_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        member = conn.execute("SELECT * FROM team_members WHERE id = ?", (member_id,)).fetchone()
        if not member:
            return None
        member_dict = dict(member)
        with conn:
            conn.execute("DELETE FROM team_members WHERE id = ?", (member_id,))
        return member_dict
    finally:
        conn.close()

# ----------------------------------------------------------------------------
# Albums & Videos Aggregation
# ----------------------------------------------------------------------------
def get_albums() -> List[dict]:
    """Returns grouped album discographies across the catalog."""
    conn = get_connection()
    try:
        query = """
            SELECT 
                COALESCE(NULLIF(t.album_name, ''), t.title || ' (Single / EP)') as album_name,
                a.id as artist_id,
                a.name as artist,
                COUNT(t.id) as track_count,
                COALESCE(SUM(t.plays_count), 0) as total_plays,
                COALESCE(SUM(t.downloads_count), 0) as total_downloads,
                MAX(t.created_at) as release_date,
                COALESCE(NULLIF((SELECT t2.cover_url FROM tracks t2 WHERE t2.artist_id = a.id AND (t2.album_name = t.album_name OR t.album_name IS NULL OR t.album_name = '') AND t2.cover_url != '' LIMIT 1), ''), '') as cover_url
            FROM tracks t
            JOIN artists a ON a.id = t.artist_id
            GROUP BY a.id, album_name
            ORDER BY total_plays DESC, release_date DESC
        """
        rows = conn.execute(query).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ----------------------------------------------------------------------------
# Music Videos Module (Full-Fidelity Video Management & Streaming)
# ----------------------------------------------------------------------------
def extract_youtube_id(url: str) -> str:
    """Extracts 11-char YouTube ID from standard, shortened, or embed URLs."""
    if not url:
        return ""
    import re
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11})',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    if len(url) == 11 and " " not in url and "/" not in url:
        return url
    return ""

def get_videos(
    genre_slug: Optional[str] = None,
    is_featured: Optional[bool] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None
) -> List[dict]:
    """Returns official music videos with optional genre filtering and search."""
    conn = get_connection()
    try:
        query = """
            SELECT 
                v.id, v.title, v.youtube_url, v.thumbnail_url, v.director,
                v.duration_seconds, v.views_count, v.downloads_count, v.is_featured,
                v.description, v.created_at,
                a.id as artist_id, a.name as artist, a.slug as artist_slug,
                g.id as genre_id, g.name as genre, g.slug as genre_slug
            FROM videos v
            JOIN artists a ON a.id = v.artist_id
            JOIN genres g ON g.id = v.genre_id
            WHERE 1=1
        """
        params = []
        if genre_slug:
            query += " AND g.slug = ?"
            params.append(genre_slug.lower())
        if is_featured is not None:
            query += " AND v.is_featured = ?"
            params.append(1 if is_featured else 0)
        if search:
            query += " AND (v.title LIKE ? OR a.name LIKE ?)"
            s_pat = f"%{search}%"
            params.extend([s_pat, s_pat])

        query += " ORDER BY v.is_featured DESC, v.views_count DESC, v.id DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

        rows = conn.execute(query, tuple(params)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            yt_id = extract_youtube_id(d.get("youtube_url", ""))
            d["youtube_id"] = yt_id
            if not d.get("thumbnail_url") and yt_id:
                d["thumbnail_url"] = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
            result.append(d)
        return result
    finally:
        conn.close()

def get_video_by_id(video_id: int) -> Optional[dict]:
    """Retrieves a single music video record by ID."""
    conn = get_connection()
    try:
        query = """
            SELECT 
                v.id, v.title, v.youtube_url, v.thumbnail_url, v.director,
                v.duration_seconds, v.views_count, v.downloads_count, v.is_featured,
                v.description, v.created_at,
                a.id as artist_id, a.name as artist, a.slug as artist_slug,
                g.id as genre_id, g.name as genre, g.slug as genre_slug
            FROM videos v
            JOIN artists a ON a.id = v.artist_id
            JOIN genres g ON g.id = v.genre_id
            WHERE v.id = ?
        """
        row = conn.execute(query, (video_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        yt_id = extract_youtube_id(d.get("youtube_url", ""))
        d["youtube_id"] = yt_id
        if not d.get("thumbnail_url") and yt_id:
            d["thumbnail_url"] = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"
        return d
    finally:
        conn.close()

def create_video(
    title: str,
    artist_id: int,
    genre_id: int,
    youtube_url: str,
    thumbnail_url: str = "",
    director: str = "",
    duration_seconds: int = 0,
    is_featured: bool = False,
    description: str = ""
) -> dict:
    """Creates a new music video entry."""
    conn = get_connection()
    try:
        yt_id = extract_youtube_id(youtube_url)
        if not thumbnail_url and yt_id:
            thumbnail_url = f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg"

        with conn:
            cur = conn.execute("""
                INSERT INTO videos (title, artist_id, genre_id, youtube_url, thumbnail_url, director, duration_seconds, is_featured, description)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title.strip(), artist_id, genre_id, youtube_url.strip(), thumbnail_url.strip(), director.strip(), duration_seconds, 1 if is_featured else 0, description.strip()))
            new_id = cur.lastrowid
        return get_video_by_id(new_id)
    finally:
        conn.close()

def update_video(
    video_id: int,
    title: Optional[str] = None,
    artist_id: Optional[int] = None,
    genre_id: Optional[int] = None,
    youtube_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    director: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    is_featured: Optional[bool] = None,
    description: Optional[str] = None
) -> Optional[dict]:
    """Updates an existing music video record."""
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
        if not existing:
            return None

        with conn:
            if title is not None:
                conn.execute("UPDATE videos SET title = ? WHERE id = ?", (title.strip(), video_id))
            if artist_id is not None:
                conn.execute("UPDATE videos SET artist_id = ? WHERE id = ?", (artist_id, video_id))
            if genre_id is not None:
                conn.execute("UPDATE videos SET genre_id = ? WHERE id = ?", (genre_id, video_id))
            if youtube_url is not None:
                conn.execute("UPDATE videos SET youtube_url = ? WHERE id = ?", (youtube_url.strip(), video_id))
                yt_id = extract_youtube_id(youtube_url)
                if yt_id and not thumbnail_url:
                    conn.execute("UPDATE videos SET thumbnail_url = ? WHERE id = ?", (f"https://img.youtube.com/vi/{yt_id}/hqdefault.jpg", video_id))
            if thumbnail_url is not None:
                conn.execute("UPDATE videos SET thumbnail_url = ? WHERE id = ?", (thumbnail_url.strip(), video_id))
            if director is not None:
                conn.execute("UPDATE videos SET director = ? WHERE id = ?", (director.strip(), video_id))
            if duration_seconds is not None:
                conn.execute("UPDATE videos SET duration_seconds = ? WHERE id = ?", (duration_seconds, video_id))
            if is_featured is not None:
                conn.execute("UPDATE videos SET is_featured = ? WHERE id = ?", (1 if is_featured else 0, video_id))
            if description is not None:
                conn.execute("UPDATE videos SET description = ? WHERE id = ?", (description.strip(), video_id))

        return get_video_by_id(video_id)
    finally:
        conn.close()

def delete_video(video_id: int) -> Optional[dict]:
    """Deletes a music video record."""
    conn = get_connection()
    try:
        v = get_video_by_id(video_id)
        if not v:
            return None
        with conn:
            conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        return v
    finally:
        conn.close()

def increment_video_views(video_id: int):
    """Increments the view count for a video."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("UPDATE videos SET views_count = views_count + 1 WHERE id = ?", (video_id,))
    finally:
        conn.close()



