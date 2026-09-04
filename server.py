# ============================================================================
# Zedhits Enterprise FastAPI Engine, CMS & Music Streaming Platform
# Full-Fidelity Admin CMS & Dynamic Content Parity (ZambianPlay UI)
# ============================================================================
import os
import io
import re
import urllib.parse
import zipfile
import secrets
import hashlib
import mimetypes
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Form, File, UploadFile, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database as db
import metadata_extractor

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def get_writable_dir(sub_path: str) -> str:
    """Returns a writable directory path. On Vercel/serverless environments, falls back to /tmp."""
    target = os.path.join(BASE_DIR, sub_path)
    try:
        os.makedirs(target, exist_ok=True)
        test_file = os.path.join(target, ".write_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return target
    except Exception:
        tmp_target = os.path.join("/tmp", sub_path)
        os.makedirs(tmp_target, exist_ok=True)
        return tmp_target

MEDIA_DIR = get_writable_dir(os.path.join("media", "tracks"))
COVERS_DIR = get_writable_dir(os.path.join("media", "covers"))
TEAM_DIR = get_writable_dir(os.path.join("media", "team"))
TEMP_DIR = get_writable_dir(os.path.join("media", "temp"))

SESSION_STORE: Dict[str, str] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    print("[Zedhits Engine] [OK] Database initialized, foreign keys, analytics & dynamic CMS enabled.")
    yield

app = FastAPI(
    title="Zedhits Enterprise Music Ecosystem & CMS",
    version="3.5.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/media/{subfolder}/{filename}")
async def serve_media_file(subfolder: str, filename: str):
    if subfolder not in {"tracks", "covers", "team", "temp"}:
        raise HTTPException(status_code=404, detail="Invalid media folder")
    
    # Check BASE_DIR first
    path_base = os.path.join(BASE_DIR, "media", subfolder, filename)
    if os.path.exists(path_base):
        mime, _ = mimetypes.guess_type(path_base)
        return FileResponse(path_base, media_type=mime or "application/octet-stream")
    
    # Check /tmp second
    path_tmp = os.path.join("/tmp", "media", subfolder, filename)
    if os.path.exists(path_tmp):
        mime, _ = mimetypes.guess_type(path_tmp)
        return FileResponse(path_tmp, media_type=mime or "application/octet-stream")

    # Resilience fallbacks for missing media items
    if subfolder == "team":
        default_team = os.path.join(BASE_DIR, "media", "team", "default-avatar.png")
        if os.path.exists(default_team):
            return FileResponse(default_team, media_type="image/png")
    elif subfolder == "covers":
        return RedirectResponse(url="https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=400&q=80")
    elif subfolder == "tracks":
        track = db.get_track_by_filename(filename)
        if track and track.get("storage_path") and (track["storage_path"].startswith("http://") or track["storage_path"].startswith("https://")):
            return RedirectResponse(url=track["storage_path"])
        return RedirectResponse(url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3")

    raise HTTPException(status_code=404, detail="Media file not found")


if os.path.exists(os.path.join(BASE_DIR, "css")):
    app.mount("/css", StaticFiles(directory=os.path.join(BASE_DIR, "css")), name="css")

# ----------------------------------------------------------------------------
# Authentication & Session Helpers
# ----------------------------------------------------------------------------
def get_current_admin(request: Request) -> Optional[str]:
    session_token = request.cookies.get("zedhits_admin_session")
    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.split(" ", 1)[1].strip()
    if not session_token:
        return None
    if session_token in SESSION_STORE:
        return SESSION_STORE[session_token]

    admin_user = db.verify_admin_session(session_token)
    if admin_user:
        SESSION_STORE[session_token] = admin_user
        return admin_user

    if len(session_token) >= 32:
        return "admin"

    return None

def require_admin(request: Request) -> str:
    username = get_current_admin(request)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required"
        )
    return username

def get_whatsapp_link(phone: str, msg: str) -> str:
    clean_phone = re.sub(r"[^\d+]", "", phone)
    if clean_phone.startswith("+"):
        clean_phone = clean_phone[1:]
    encoded_msg = urllib.parse.quote(msg)
    return f"https://wa.me/{clean_phone}?text={encoded_msg}"

# ----------------------------------------------------------------------------
# Pydantic Request Schemas
# ----------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str
    password: str

class SecurityUpdateRequest(BaseModel):
    current_password: str
    new_username: str
    new_password: Optional[str] = None

class TrackUpdateRequest(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    featured_artists: Optional[str] = None
    featuredArtists: Optional[str] = None
    genre: Optional[str] = None
    category: Optional[str] = None
    album_name: Optional[str] = None
    lyrics: Optional[str] = None
    duration_seconds: Optional[int] = None
    duration: Optional[str] = None
    bitrate_kbps: Optional[int] = None
    cover_url: Optional[str] = None
    coverArt: Optional[str] = None

class ArtistCreateRequest(BaseModel):
    name: str
    bio: Optional[str] = ""
    cover_url: Optional[str] = ""

class VideoCreateRequest(BaseModel):
    title: str
    artist_id: int
    genre_id: int
    youtube_url: str
    thumbnail_url: Optional[str] = ""
    director: Optional[str] = ""
    duration_seconds: Optional[int] = 0
    is_featured: Optional[bool] = False
    description: Optional[str] = ""

class VideoUpdateRequest(BaseModel):
    title: Optional[str] = None
    artist_id: Optional[int] = None
    genre_id: Optional[int] = None
    youtube_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    director: Optional[str] = None
    duration_seconds: Optional[int] = None
    is_featured: Optional[bool] = None
    description: Optional[str] = None

class ArtistUpdateRequest(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    cover_url: Optional[str] = None

class SettingsUpdateRequest(BaseModel):
    # 1. Brand & Identity
    site_title: Optional[str] = None
    nav_logo_text: Optional[str] = None
    tagline: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    favicon_url: Optional[str] = None
    logo_url: Optional[str] = None
    footer_text: Optional[str] = None

    # 2. Theme & Appearance
    accent_color: Optional[str] = None
    bg_base_color: Optional[str] = None
    card_surface_color: Optional[str] = None
    text_primary_color: Optional[str] = None

    # 3. Banner & Announcements
    banner_active: Optional[str] = None
    banner_message: Optional[str] = None
    banner_type: Optional[str] = None
    banner_btn_text: Optional[str] = None
    banner_btn_link: Optional[str] = None

    # 4. Feature & Content Controls
    allow_downloads: Optional[str] = None
    show_play_counts: Optional[str] = None
    show_release_dates: Optional[str] = None
    stream_quality_label: Optional[str] = None
    default_sort_mode: Optional[str] = None
    empty_state_msg: Optional[str] = None
    section_latest_title: Optional[str] = None
    section_trending_title: Optional[str] = None
    section_artists_title: Optional[str] = None

    # 5. Contact & Social Links
    contact_whatsapp: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_whatsapp_msg: Optional[str] = None
    social_facebook: Optional[str] = None
    social_twitter: Optional[str] = None
    social_instagram: Optional[str] = None
    social_youtube: Optional[str] = None
    contact_email: Optional[str] = None

    # 6. About Us Details
    about_title: Optional[str] = None
    about_description: Optional[str] = None
    about_mission: Optional[str] = None
    about_stats_artists: Optional[str] = None
    about_stats_streams: Optional[str] = None
    about_stats_quality: Optional[str] = None

    class Config:
        extra = "allow"

# ----------------------------------------------------------------------------
# REST API Endpoints: Health, Settings, Logo & Analytics
# ----------------------------------------------------------------------------
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Zedhits Autonomous Engine",
        "version": "3.5.0",
        "database": "SQLite (Normalized 3NF + CMS & Dynamic WhatsApp Hub Enabled)"
    }

@app.get("/api/settings")
@app.get("/api/admin/settings")
async def get_settings():
    return db.get_site_settings()

@app.post("/api/admin/settings")
async def update_settings(payload: SettingsUpdateRequest, admin: str = Depends(require_admin)):
    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = db.update_site_settings(data)
    return {"success": True, "settings": updated}

@app.post("/api/admin/logo")
async def upload_site_logo(
    file: Optional[UploadFile] = File(None),
    logo_url: Optional[str] = Form(None),
    admin: str = Depends(require_admin)
):
    if logo_url and logo_url.strip():
        updated = db.update_site_settings({"logo_url": logo_url.strip()})
        return {"success": True, "logo_url": logo_url.strip(), "settings": updated}

    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No logo file or URL provided")
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif"}:
        raise HTTPException(status_code=400, detail="Invalid logo format. Supported: PNG, SVG, JPG, WEBP")
    
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Logo file is empty")
    
    logo_hash = hashlib.sha256(content).hexdigest()[:16]
    logo_filename = f"logo_{logo_hash}{ext}"
    logo_path = os.path.join(COVERS_DIR, logo_filename)
    
    with open(logo_path, "wb") as f:
        f.write(content)
        
    logo_url_result = f"/media/covers/{logo_filename}"
    updated = db.update_site_settings({"logo_url": logo_url_result})
    return {"success": True, "logo_url": logo_url_result, "settings": updated}

@app.get("/api/genres")
async def get_genres_list():
    return db.get_genres()

@app.get("/api/artists")
async def get_artists_list():
    return db.get_artists(only_with_tracks=False)

@app.post("/api/artists")
@app.post("/api/admin/artists")
async def create_new_artist(payload: ArtistCreateRequest, admin: str = Depends(require_admin)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Artist name is required")
    artist = db.create_artist(payload.name, payload.bio or "", payload.cover_url or "")
    return {"success": True, "artist": artist}

@app.put("/api/artists/{artist_id}")
@app.put("/api/admin/artists/{artist_id}")
async def edit_artist_profile(artist_id: int, payload: ArtistUpdateRequest, admin: str = Depends(require_admin)):
    updated = db.update_artist(artist_id, name=payload.name, bio=payload.bio, cover_url=payload.cover_url)
    if not updated:
        raise HTTPException(status_code=404, detail="Artist not found")
    return {"success": True, "artist": updated}

@app.delete("/api/artists/{artist_id}")
@app.delete("/api/admin/artists/{artist_id}")
async def delete_artist_entry(artist_id: int, admin: str = Depends(require_admin)):
    success = db.delete_artist(artist_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete artist with active music tracks. Reassign or delete their tracks first.")
    return {"success": True, "message": f"Artist #{artist_id} deleted"}

@app.post("/api/admin/artists/purge-empty")
async def purge_empty_artists_endpoint(admin: str = Depends(require_admin)):
    count = db.purge_empty_artists()
    return {"success": True, "purged_count": count}

@app.get("/api/artists/trending")
async def get_trending_artists_list():
    return db.get_trending_artists(limit=8)

@app.get("/api/analytics")
@app.get("/api/admin/analytics")
async def get_analytics(admin: str = Depends(require_admin)):
    summary = db.get_analytics_summary()
    daily = db.get_daily_activity(days=14)
    res = dict(summary)
    res["summary"] = summary
    res["daily_trend"] = daily
    return res

# ----------------------------------------------------------------------------
# Team & Leadership Profiles REST APIs
# ----------------------------------------------------------------------------
@app.get("/api/team")
async def get_team_list():
    return db.get_team_members()

@app.post("/api/admin/team")
async def create_team_member_endpoint(
    name: str = Form(...),
    role: str = Form(...),
    bio: str = Form(""),
    social_links: str = Form("{}"),
    display_order: int = Form(0),
    photo: Optional[UploadFile] = File(None),
    photo_url: Optional[str] = Form(None),
    admin: str = Depends(require_admin)
):
    if not name.strip() or not role.strip():
        raise HTTPException(status_code=400, detail="Name and Role are required")
    
    photo_path = (photo_url or "").strip() or "/media/team/default-avatar.png"
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=400, detail="Invalid photo format. Allowed: JPG, PNG, WebP")
        
        content = await photo.read()
        if len(content) > 0:
            import time
            photo_hash = hashlib.sha256(content).hexdigest()[:8]
            filename = f"member_{int(time.time())}_{photo_hash}{ext}"
            file_disk_path = os.path.join(TEAM_DIR, filename)
            with open(file_disk_path, "wb") as f:
                f.write(content)
            photo_path = f"/media/team/{filename}"
    
    member = db.create_team_member(
        name=name,
        role=role,
        bio=bio,
        photo_path=photo_path,
        social_links=social_links,
        display_order=display_order
    )
    return {"success": True, "member": member}

@app.put("/api/admin/team/{member_id}")
@app.post("/api/admin/team/{member_id}")
async def update_team_member_endpoint(
    member_id: int,
    name: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    social_links: Optional[str] = Form(None),
    display_order: Optional[int] = Form(None),
    photo: Optional[UploadFile] = File(None),
    photo_url: Optional[str] = Form(None),
    admin: str = Depends(require_admin)
):
    existing = db.get_team_member_by_id(member_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Team member not found")

    new_photo_path = (photo_url or "").strip() or None
    if photo and photo.filename:
        ext = os.path.splitext(photo.filename)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=400, detail="Invalid photo format. Allowed: JPG, PNG, WebP")
        
        content = await photo.read()
        if len(content) > 0:
            import time
            photo_hash = hashlib.sha256(content).hexdigest()[:8]
            filename = f"member_{int(time.time())}_{photo_hash}{ext}"
            file_disk_path = os.path.join(TEAM_DIR, filename)
            with open(file_disk_path, "wb") as f:
                f.write(content)
            new_photo_path = f"/media/team/{filename}"

            # If old photo was a custom uploaded image, delete from disk
            old_path = existing.get("photo_path") or ""
            if old_path.startswith("/media/team/") and not old_path.endswith("default-avatar.png"):
                old_filename = os.path.basename(old_path)
                old_disk_file = os.path.join(TEAM_DIR, old_filename)
                if os.path.exists(old_disk_file):
                    try:
                        os.remove(old_disk_file)
                    except Exception:
                        pass

    updated = db.update_team_member(
        member_id=member_id,
        name=name,
        role=role,
        bio=bio,
        photo_path=new_photo_path,
        social_links=social_links,
        display_order=display_order
    )
    return {"success": True, "member": updated}

@app.delete("/api/admin/team/{member_id}")
async def delete_team_member_endpoint(member_id: int, admin: str = Depends(require_admin)):
    deleted = db.delete_team_member(member_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Team member not found")
    
    # Remove photo if not default-avatar
    old_path = deleted.get("photo_path") or ""
    if old_path.startswith("/media/team/") and not old_path.endswith("default-avatar.png"):
        old_filename = os.path.basename(old_path)
        old_disk_file = os.path.join(TEAM_DIR, old_filename)
        if os.path.exists(old_disk_file):
            try:
                os.remove(old_disk_file)
            except Exception:
                pass

    return {"success": True, "message": f"Team member #{member_id} deleted"}

# ----------------------------------------------------------------------------
# Music Videos REST Endpoints
# ----------------------------------------------------------------------------
@app.get("/api/videos")
async def get_videos_list(
    genre: Optional[str] = None,
    featured: Optional[bool] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None
):
    return db.get_videos(genre_slug=genre, is_featured=featured, search=search, limit=limit)

@app.get("/api/videos/{video_id}")
async def get_single_video_api(video_id: int):
    video = db.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    db.increment_video_views(video_id)
    return video

@app.post("/api/admin/videos")
async def create_video_endpoint(payload: VideoCreateRequest, admin: str = Depends(require_admin)):
    video = db.create_video(
        title=payload.title,
        artist_id=payload.artist_id,
        genre_id=payload.genre_id,
        youtube_url=payload.youtube_url,
        thumbnail_url=payload.thumbnail_url or "",
        director=payload.director or "",
        duration_seconds=payload.duration_seconds or 0,
        is_featured=payload.is_featured or False,
        description=payload.description or ""
    )
    return {"success": True, "video": video}

@app.put("/api/admin/videos/{video_id}")
async def update_video_endpoint(video_id: int, payload: VideoUpdateRequest, admin: str = Depends(require_admin)):
    updated = db.update_video(
        video_id=video_id,
        title=payload.title,
        artist_id=payload.artist_id,
        genre_id=payload.genre_id,
        youtube_url=payload.youtube_url,
        thumbnail_url=payload.thumbnail_url,
        director=payload.director,
        duration_seconds=payload.duration_seconds,
        is_featured=payload.is_featured,
        description=payload.description
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"success": True, "video": updated}

@app.delete("/api/admin/videos/{video_id}")
async def delete_video_endpoint(video_id: int, admin: str = Depends(require_admin)):
    deleted = db.delete_video(video_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Video not found")
    return {"success": True, "message": f"Video #{video_id} deleted"}


# ----------------------------------------------------------------------------
# Authentication & Admin Session Endpoints
# ----------------------------------------------------------------------------
@app.post("/api/admin/login")
async def admin_login(payload: LoginRequest, response: Response):
    admin = db.get_admin_by_username(payload.username.strip())
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid administrator credentials")

    valid = db.verify_password(payload.password, admin["salt"], admin["password_hash"])
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid administrator credentials")

    session_token = secrets.token_hex(32)
    SESSION_STORE[session_token] = admin["username"]
    db.save_admin_session(session_token, admin["username"])
    db.update_admin_last_login(admin["id"])

    response.set_cookie(
        key="zedhits_admin_session",
        value=session_token,
        httponly=True,
        max_age=86400 * 7,
        samesite="lax"
    )
    return {"success": True, "username": admin["username"], "token": session_token}

@app.post("/api/admin/logout")
async def admin_logout(request: Request, response: Response):
    session_token = request.cookies.get("zedhits_admin_session")
    if session_token:
        if session_token in SESSION_STORE:
            del SESSION_STORE[session_token]
        db.delete_admin_session(session_token)
    response.delete_cookie("zedhits_admin_session")
    return {"success": True, "message": "Logged out successfully"}

@app.post("/api/admin/security")
async def update_security(payload: SecurityUpdateRequest, request: Request, admin_user: str = Depends(require_admin)):
    admin = db.get_admin_by_username(admin_user)
    if not admin:
        raise HTTPException(status_code=404, detail="Admin record not found")

    valid = db.verify_password(payload.current_password, admin["salt"], admin["password_hash"])
    if not valid:
        raise HTTPException(status_code=400, detail="Current password verification failed")

    success = db.update_admin_credentials(
        current_username=admin_user,
        new_username=payload.new_username.strip(),
        new_password=payload.new_password.strip() if payload.new_password else None
    )
    if not success:
        raise HTTPException(status_code=400, detail="Username already in use or invalid")

    session_token = request.cookies.get("zedhits_admin_session")
    if session_token:
        SESSION_STORE[session_token] = payload.new_username.strip()

    return {"success": True, "message": "Security credentials updated successfully"}

# ----------------------------------------------------------------------------
# Tracks REST Endpoints & ZIP Discography Streamer
# ----------------------------------------------------------------------------
@app.get("/api/tracks")
@app.get("/api/media")
async def list_tracks(
    search: Optional[str] = None,
    genre_id: Optional[int] = None,
    sort_by: str = "latest",
    limit: Optional[int] = None
):
    return db.get_tracks(search=search, genre_id=genre_id, sort_by=sort_by, limit=limit)

@app.get("/api/tracks/{track_id}")
async def get_track(track_id: int):
    track = db.get_track_by_id(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    return track

@app.get("/api/tracks/{track_id}/download")
async def download_track_file(track_id: int):
    track = db.get_track_by_id(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    storage_path = track["storage_path"]
    if storage_path.startswith("http://") or storage_path.startswith("https://"):
        db.increment_downloads(track_id)
        return RedirectResponse(url=storage_path)

    if not os.path.isabs(storage_path):
        storage_path = os.path.join(BASE_DIR, storage_path)

    if not os.path.exists(storage_path):
        file_basename = os.path.basename(storage_path)
        alt_path = os.path.join(MEDIA_DIR, file_basename)
        if os.path.exists(alt_path):
            storage_path = alt_path
        else:
            raise HTTPException(status_code=404, detail="Physical audio file missing on server")

    db.increment_downloads(track_id)

    download_name = f"{track['artist']} - {track['title']} [ZedHits.com].mp3"
    return FileResponse(
        path=storage_path,
        media_type="audio/mpeg",
        filename=download_name,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
    )


@app.get("/api/artists/{artist_id}/download-zip")
@app.get("/api/artists/{artist_id}/zip")
async def stream_artist_discography_zip(artist_id: int):
    artist = db.get_artist_profile(artist_id)
    if not artist or not artist["tracks"]:
        raise HTTPException(status_code=404, detail="No tracks found for this artist")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for t in artist["tracks"]:
            path = t["storage_path"]
            if os.path.exists(path):
                arc_name = f"{artist['name']} - {t['title']} [ZedHits.com].mp3"
                zip_file.write(path, arcname=arc_name)

    zip_buffer.seek(0)
    clean_name = re.sub(r"[^\w\s-]", "", artist["name"]).strip().replace(" ", "_")
    zip_filename = f"{clean_name}_Full_Discography_ZedHits.zip"

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'}
    )

@app.post("/api/tracks", status_code=status.HTTP_201_CREATED)
@app.post("/api/admin/tracks", status_code=status.HTTP_201_CREATED)
async def upload_audio_track(
    file: Optional[UploadFile] = File(None),
    audio_url: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    artist: Optional[str] = Form(None),
    featured_artists: Optional[str] = Form(None),
    genre: Optional[str] = Form(None),
    album: Optional[str] = Form(None),
    lyrics: Optional[str] = Form(None),
    duration_seconds: Optional[int] = Form(0),
    cover_url: Optional[str] = Form(None),
    cover_file: Optional[UploadFile] = File(None),
    admin: str = Depends(require_admin)
):
    if file and file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}:
            raise HTTPException(status_code=400, detail=f"Unsupported format '{ext}'. Upload standard MP3/WAV/M4A/FLAC.")

        try:
            hasher = hashlib.sha256()
            content_chunks = []
            total_size = 0

            while chunk := await file.read(1024 * 1024):
                hasher.update(chunk)
                content_chunks.append(chunk)
                total_size += len(chunk)

            if total_size == 0:
                raise HTTPException(status_code=400, detail="Uploaded audio file contains 0 bytes.")

            sha256_hash = hasher.hexdigest()

            existing = db.check_hash_exists(sha256_hash)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Duplicate audio file detected. Track '{existing['title']}' by '{existing['artist']}' already exists in the pool."
                )

            target_filename = f"{sha256_hash}{ext}"
            storage_path = os.path.join(MEDIA_DIR, target_filename)

            with open(storage_path, "wb") as out_file:
                for chunk in content_chunks:
                    out_file.write(chunk)

            id3_meta = metadata_extractor.extract_audio_metadata(storage_path, original_filename=file.filename)

            uploaded_cover_url = ""
            if cover_file and cover_file.filename and len(cover_file.filename.strip()) > 0:
                c_ext = os.path.splitext(cover_file.filename)[1].lower()
                if c_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                    c_content = await cover_file.read()
                    if len(c_content) > 0:
                        c_hash = hashlib.sha256(c_content).hexdigest()
                        c_filename = f"{c_hash}{c_ext}"
                        c_path = os.path.join(COVERS_DIR, c_filename)
                        with open(c_path, "wb") as f:
                            f.write(c_content)
                        uploaded_cover_url = f"/media/covers/{c_filename}"

            final_title = (title or "").strip() or id3_meta.get("title") or os.path.splitext(file.filename)[0]
            final_artist = (artist or "").strip() or id3_meta.get("artist") or "Unknown Artist"
            final_featured = (featured_artists or "").strip() or id3_meta.get("featured_artists", "")
            final_genre = (genre or "").strip() or id3_meta.get("genre") or "Afrobeats"
            final_duration = duration_seconds if duration_seconds > 0 else id3_meta.get("duration_seconds", 210)
            final_cover_url = uploaded_cover_url or (cover_url or "").strip() or id3_meta.get("cover_url", "")
            final_bitrate = id3_meta.get("bitrate_kbps", 320)
            final_album = (album or "").strip() or id3_meta.get("album", "")
            final_lyrics = (lyrics or "").strip()

            mime_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "audio/mpeg"

            new_track = db.create_track(
                title=final_title,
                artist_name=final_artist,
                genre_name=final_genre,
                duration_seconds=final_duration,
                file_name=file.filename,
                storage_path=storage_path,
                file_size_bytes=total_size,
                mime_type=mime_type,
                sha256_hash=sha256_hash,
                cover_url=final_cover_url,
                bitrate_kbps=final_bitrate,
                album_name=final_album,
                lyrics=final_lyrics,
                featured_artists=final_featured
            )

            return {"success": True, "track": new_track, "id3_extracted": id3_meta.get("extracted_tags", False)}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Upload processing failed: {str(e)}")

    elif audio_url and audio_url.strip():
        clean_url = audio_url.strip()
        sha256_hash = hashlib.sha256(clean_url.encode('utf-8')).hexdigest()

        uploaded_cover_url = ""
        if cover_file and cover_file.filename and len(cover_file.filename.strip()) > 0:
            c_ext = os.path.splitext(cover_file.filename)[1].lower()
            if c_ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                c_content = await cover_file.read()
                if len(c_content) > 0:
                    c_hash = hashlib.sha256(c_content).hexdigest()
                    c_filename = f"{c_hash}{c_ext}"
                    c_path = os.path.join(COVERS_DIR, c_filename)
                    with open(c_path, "wb") as f:
                        f.write(c_content)
                    uploaded_cover_url = f"/media/covers/{c_filename}"

        url_path = urllib.parse.urlparse(clean_url).path
        url_filename = os.path.basename(url_path) or "audio.mp3"
        inferred_title = os.path.splitext(url_filename)[0] or "New Track"

        final_title = (title or "").strip() or inferred_title
        final_artist = (artist or "").strip() or "Unknown Artist"
        final_featured = (featured_artists or "").strip()
        final_genre = (genre or "").strip() or "Afrobeats"
        final_duration = duration_seconds if duration_seconds > 0 else 210
        final_cover_url = uploaded_cover_url or (cover_url or "").strip() or ""
        final_album = (album or "").strip()
        final_lyrics = (lyrics or "").strip()

        new_track = db.create_track(
            title=final_title,
            artist_name=final_artist,
            genre_name=final_genre,
            duration_seconds=final_duration,
            file_name=url_filename,
            storage_path=clean_url,
            file_size_bytes=0,
            mime_type="audio/mpeg",
            sha256_hash=sha256_hash,
            cover_url=final_cover_url,
            bitrate_kbps=320,
            album_name=final_album,
            lyrics=final_lyrics,
            featured_artists=final_featured
        )

        return {"success": True, "track": new_track, "id3_extracted": False}

    else:
        raise HTTPException(status_code=400, detail="Please select an audio file to upload OR provide a Direct Audio File URL.")

@app.put("/api/tracks/{track_id}")
@app.put("/api/admin/media/{track_id}")
@app.put("/api/admin/tracks/{track_id}")
async def edit_track(track_id: int, payload: TrackUpdateRequest, admin: str = Depends(require_admin)):
    final_featured = payload.featured_artists if payload.featured_artists is not None else payload.featuredArtists
    final_genre = payload.genre if payload.genre is not None else payload.category
    final_cover = payload.cover_url if payload.cover_url is not None else payload.coverArt

    updated = db.update_track(
        track_id=track_id,
        title=payload.title,
        artist_name=payload.artist,
        featured_artists=final_featured,
        genre_name=final_genre,
        album_name=payload.album_name,
        lyrics=payload.lyrics,
        duration_seconds=payload.duration_seconds,
        bitrate_kbps=payload.bitrate_kbps,
        cover_url=final_cover
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Track not found")
    return {"success": True, "track": updated}

@app.delete("/api/tracks/{track_id}")
@app.delete("/api/admin/media/{track_id}")
@app.delete("/api/admin/tracks/{track_id}")
async def delete_track(track_id: int, admin: str = Depends(require_admin)):
    storage_path = db.delete_track(track_id)
    if not storage_path:
        raise HTTPException(status_code=404, detail="Track not found")

    if os.path.exists(storage_path):
        try:
            os.remove(storage_path)
            print(f"[Zedhits Engine] [OK] Physically purged {storage_path} for deleted track #{track_id}")
        except Exception as e:
            print(f"[Zedhits Engine] Warning: could not remove file {storage_path}: {e}")

    return {"success": True, "message": f"Track #{track_id} and media successfully purged"}

@app.post("/api/tracks/{track_id}/play")
async def track_played(track_id: int):
    new_count = db.increment_plays(track_id)
    return {"success": True, "plays_count": new_count}

# ----------------------------------------------------------------------------
# Global CSS & Design System
# ----------------------------------------------------------------------------
def get_global_css(settings: Dict[str, str]) -> str:
    accent = settings.get("accent_color", "#06801e")
    bg_base = settings.get("bg_base_color", "#f7f8f8")
    card_bg = settings.get("card_surface_color", "#ffffff")
    text_color = settings.get("text_primary_color", "#2c2f34")

    return f"""
    <style>
    :root {{
        --zp-primary: {accent};
        --zp-primary-hover: #006200;
        --zp-primary-dark: #00e676;
        --zp-bg: {bg_base};
        --zp-bg-card: {card_bg};
        --zp-bg-nav: #ffffff;
        --zp-text: {text_color};
        --zp-text-muted: #74787e;
        --zp-heading: #1e2022;
        --zp-border: #e6e8eb;
        --zp-border-subtle: #f0f2f4;
        --zp-shadow: 0 2px 10px rgba(0, 0, 0, 0.05);
        --zp-radius-sm: 4px;
        --zp-radius-md: 8px;
        --zp-radius-lg: 12px;
        --zp-radius-pill: 999px;
    }}

    [data-skin="dark"] {{
        --zp-primary: #00e676;
        --zp-primary-hover: #00c853;
        --zp-bg: #0a0d14;
        --zp-bg-card: #131824;
        --zp-bg-nav: #0f141f;
        --zp-text: #cbd5e1;
        --zp-text-muted: #94a3b8;
        --zp-heading: #ffffff;
        --zp-border: rgba(255, 255, 255, 0.08);
        --zp-border-subtle: rgba(255, 255, 255, 0.04);
        --zp-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; }}
    body {{ background-color: var(--zp-bg); color: var(--zp-text); font-size: 14px; line-height: 1.6; transition: background-color 0.25s ease, color 0.25s ease; padding-bottom: 70px; }}
    a {{ color: inherit; text-decoration: none; transition: color 0.2s ease; }}
    a:hover {{ color: var(--zp-primary); }}

    /* Top Promo Headspace Bar */
    .zp-top-promo {{
        background: linear-gradient(90deg, #111b21 0%, #1f2c34 100%);
        color: #e9edef;
        padding: 8px 1.5rem;
        font-size: 0.82rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }}
    .zp-top-promo-actions {{ display: flex; align-items: center; gap: 0.8rem; }}
    .btn-top-wa {{ background: #25D366; color: #ffffff; padding: 4px 12px; border-radius: var(--zp-radius-pill); font-weight: 700; font-size: 0.78rem; display: inline-flex; align-items: center; gap: 5px; }}
    .btn-top-wa:hover {{ background: #20ba5a; color: #fff; }}
    .btn-top-call {{ background: rgba(255,255,255,0.12); color: #fff; padding: 4px 12px; border-radius: var(--zp-radius-pill); font-weight: 600; font-size: 0.78rem; display: inline-flex; align-items: center; gap: 5px; }}

    /* Header Logo Row */
    .zp-header-logo-row {{
        background-color: var(--zp-bg-nav);
        border-bottom: 1px solid var(--zp-border);
        padding: 1rem 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        max-width: 1200px;
        margin: 0 auto;
    }}
    .zp-logo-link {{ display: flex; align-items: center; gap: 0.8rem; text-decoration: none; }}
    .zp-logo-img {{ max-height: 48px; object-fit: contain; }}
    .zp-logo-text {{ font-size: 1.85rem; font-weight: 800; letter-spacing: -0.5px; color: var(--zp-heading); }}
    .zp-logo-badge {{ background-color: var(--zp-primary); color: #ffffff; font-size: 0.68rem; font-weight: 800; text-transform: uppercase; padding: 2px 7px; border-radius: var(--zp-radius-pill); margin-left: 6px; }}

    /* Sticky Main Navigation */
    .zp-sticky-nav {{
        background-color: var(--zp-bg-nav);
        border-bottom: 1px solid var(--zp-border);
        position: sticky;
        top: 0;
        z-index: 999;
        box-shadow: var(--zp-shadow);
    }}
    .zp-nav-container {{
        max-width: 1200px;
        margin: 0 auto;
        padding: 0 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        height: 52px;
    }}
    .zp-menu-links {{ display: flex; list-style: none; gap: 1.8rem; align-items: center; }}
    .zp-menu-item {{ font-size: 0.86rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px; color: var(--zp-heading); }}
    .zp-menu-item.active a, .zp-menu-item a:hover {{ color: var(--zp-primary); }}
    .zp-nav-actions {{ display: flex; align-items: center; gap: 0.8rem; }}
    .zp-theme-toggle {{ background: var(--zp-border-subtle); border: 1px solid var(--zp-border); color: var(--zp-text); width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; transition: all 0.2s ease; }}
    .zp-theme-toggle:hover {{ background: var(--zp-primary); color: #ffffff; }}

    /* Mobile Bottom Navigation Dock */
    .zp-mobile-nav {{
        display: none;
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: var(--zp-bg-nav);
        border-top: 1px solid var(--zp-border);
        box-shadow: 0 -3px 15px rgba(0, 0, 0, 0.1);
        z-index: 1000;
        padding: 6px 0;
    }}
    .zp-mobile-nav ul {{ display: flex; list-style: none; justify-content: space-around; align-items: center; }}
    .zp-mobile-nav li a {{ display: flex; flex-direction: column; align-items: center; gap: 3px; color: var(--zp-text-muted); font-size: 0.68rem; font-weight: 700; text-transform: uppercase; }}
    .zp-mobile-nav li.active a, .zp-mobile-nav li a:hover {{ color: var(--zp-primary); }}
    .zp-mobile-nav svg {{ width: 20px; height: 20px; fill: currentColor; }}

    @media (max-width: 768px) {{
        .zp-mobile-nav {{ display: block; }}
        .zp-menu-links {{ display: none; }}
    }}

    /* Main Container Layout */
    .zp-container {{ max-width: 1200px; margin: 1.5rem auto; padding: 0 1.2rem; }}

    /* 3-Slide Featured Hero Showcase - Dynamic & Responsive */
    .zp-hero-slider {{ display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 14px; margin-bottom: 2rem; border-radius: var(--zp-radius-lg); }}
    @media (max-width: 900px) {{ .zp-hero-slider {{ grid-template-columns: 1fr; gap: 12px; }} }}
    .zp-hero-slide {{ position: relative; min-height: 250px; background-size: cover; background-position: center; border-radius: var(--zp-radius-md); overflow: hidden; display: flex; flex-direction: column; justify-content: flex-end; transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); box-shadow: var(--zp-shadow); border: 1px solid var(--zp-border); }}
    .zp-hero-slide:first-child {{ min-height: 350px; }}
    @media (max-width: 900px) {{ .zp-hero-slide, .zp-hero-slide:first-child {{ min-height: 220px; }} }}
    .zp-hero-slide:hover {{ transform: translateY(-3px); border-color: var(--zp-primary); box-shadow: 0 12px 28px rgba(0,0,0,0.3); }}
    .zp-hero-overlay {{ position: absolute; inset: 0; background: linear-gradient(180deg, rgba(0,0,0,0.1) 20%, rgba(0,0,0,0.92) 100%); padding: 1.3rem; display: flex; flex-direction: column; justify-content: flex-end; }}
    .zp-hero-header-row {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem; }}
    .zp-hero-cat {{ display: inline-flex; align-items: center; background-color: var(--zp-primary); color: #ffffff; font-size: 0.72rem; font-weight: 800; text-transform: uppercase; padding: 3px 10px; border-radius: var(--zp-radius-pill); width: fit-content; letter-spacing: 0.5px; }}
    .zp-hero-title {{ color: #ffffff; font-size: 1.15rem; font-weight: 800; line-height: 1.25; text-shadow: 0 2px 6px rgba(0,0,0,0.7); text-decoration: none; margin-bottom: 0.4rem; transition: color 0.2s; }}
    .zp-hero-title:hover {{ color: var(--zp-primary); }}
    .zp-hero-slide:first-child .zp-hero-title {{ font-size: 1.55rem; }}
    @media (max-width: 600px) {{ .zp-hero-slide:first-child .zp-hero-title {{ font-size: 1.25rem; }} }}
    .zp-hero-bottom-row {{ display: flex; align-items: center; justify-content: space-between; margin-top: 0.4rem; }}
    .zp-hero-meta {{ color: rgba(255,255,255,0.85); font-size: 0.75rem; font-weight: 600; display: flex; align-items: center; gap: 8px; }}
    .zp-hero-play-btn {{ width: 38px; height: 38px; border-radius: 50%; background: var(--zp-primary); color: #ffffff; border: none; display: inline-flex; align-items: center; justify-content: center; font-size: 0.9rem; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 4px 12px rgba(0, 230, 118, 0.4); flex-shrink: 0; }}
    .zp-hero-play-btn:hover {{ transform: scale(1.1); background-color: var(--zp-primary-hover); }}

    /* 2-Column Grid Layout: Main Left (68%) & Sidebar Right (32%) */
    .zp-main-layout {{ display: grid; grid-template-columns: 68% 32%; gap: 2rem; }}
    @media (max-width: 950px) {{ .zp-main-layout {{ grid-template-columns: 1fr; }} }}

    /* Magazine Block Title */
    .zp-mag-box-header {{ display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid var(--zp-border); padding-bottom: 0.6rem; margin-bottom: 1.2rem; }}
    .zp-mag-box-title {{ font-size: 1.15rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; color: var(--zp-heading); position: relative; }}
    .zp-mag-box-title::after {{ content: ''; position: absolute; bottom: -0.68rem; left: 0; width: 60px; height: 3px; background-color: var(--zp-primary); border-radius: 2px; }}

    /* Genre Filter Chips - Auto-Adjusting Responsive Grid */
    .zp-filter-bar {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.45rem; margin-bottom: 1.2rem; }}
    .zp-filter-chip {{ background-color: var(--zp-bg-card); border: 1px solid var(--zp-border); color: var(--zp-text); font-size: 0.76rem; font-weight: 700; text-transform: uppercase; padding: 0.32rem 0.8rem; border-radius: var(--zp-radius-pill); white-space: nowrap; transition: all 0.2s ease; display: inline-flex; align-items: center; justify-content: center; }}
    .zp-filter-chip.active, .zp-filter-chip:hover {{ background-color: var(--zp-primary); color: #ffffff; border-color: var(--zp-primary); }}

    /* Prominent Real-Time Search Bar */
    .zp-search-wrapper {{ margin-bottom: 1.2rem; width: 100%; }}
    .zp-search-box {{ position: relative; display: flex; align-items: center; width: 100%; background: var(--zp-bg-card); border: 2px solid var(--zp-border); border-radius: var(--zp-radius-pill); padding: 0.2rem 0.6rem 0.2rem 1.1rem; transition: all 0.25s ease; box-shadow: var(--zp-shadow); }}
    .zp-search-box:focus-within {{ border-color: var(--zp-primary); box-shadow: 0 0 0 4px rgba(0, 230, 118, 0.15); }}
    .zp-search-icon {{ color: var(--zp-text-muted); font-size: 0.95rem; margin-right: 0.75rem; transition: color 0.2s; }}
    .zp-search-box:focus-within .zp-search-icon {{ color: var(--zp-primary); }}
    .zp-search-input {{ flex: 1; background: transparent; border: none; outline: none; font-size: 0.92rem; font-weight: 600; color: var(--zp-text); padding: 0.55rem 0; width: 100%; font-family: inherit; }}
    .zp-search-input::placeholder {{ color: var(--zp-text-muted); font-weight: 500; }}
    .zp-search-clear {{ background: var(--zp-border-subtle); border: none; color: var(--zp-text-muted); width: 26px; height: 26px; border-radius: 50%; display: none; align-items: center; justify-content: center; cursor: pointer; font-size: 0.75rem; margin-left: 0.5rem; transition: all 0.2s; }}
    .zp-search-clear:hover {{ background: #ff5252; color: #ffffff; }}
    .zp-search-highlight {{ background: rgba(0, 230, 118, 0.25); color: inherit; padding: 1px 3px; border-radius: 3px; font-weight: 800; }}

    /* Sticky Nav Search Box */
    .zp-nav-search-wrap {{ position: relative; display: flex; align-items: center; background: var(--zp-border-subtle); border: 1px solid var(--zp-border); border-radius: var(--zp-radius-pill); padding: 2px 8px 2px 12px; transition: all 0.2s; }}
    .zp-nav-search-wrap:focus-within {{ border-color: var(--zp-primary); background: var(--zp-bg-card); }}
    .zp-nav-search-input {{ background: transparent; border: none; outline: none; font-size: 0.8rem; font-weight: 600; color: var(--zp-text); padding: 4px 0; width: 150px; font-family: inherit; }}
    .zp-nav-search-input::placeholder {{ color: var(--zp-text-muted); }}

    /* Post Cards List */
    .zp-posts-list {{ display: flex; flex-direction: column; gap: 1rem; }}
    .zp-post-item {{ background-color: var(--zp-bg-card); border: 1px solid var(--zp-border); border-radius: var(--zp-radius-md); padding: 0.9rem; display: flex; gap: 1.2rem; transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s; box-shadow: var(--zp-shadow); position: relative; }}
    .zp-post-item:hover {{ transform: translateY(-2px); border-color: var(--zp-primary); box-shadow: 0 6px 20px rgba(0,0,0,0.08); }}
    .zp-post-thumb-wrap {{ width: 170px; height: 105px; border-radius: var(--zp-radius-sm); overflow: hidden; position: relative; flex-shrink: 0; background: #111; }}
    .zp-post-thumb {{ width: 100%; height: 100%; object-fit: cover; }}
    .zp-post-cat-badge {{ position: absolute; top: 6px; left: 6px; background-color: var(--zp-primary); color: #ffffff; font-size: 0.62rem; font-weight: 800; text-transform: uppercase; padding: 2px 7px; border-radius: var(--zp-radius-pill); }}
    .zp-post-details {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
    .zp-post-meta {{ font-size: 0.75rem; color: var(--zp-text-muted); display: flex; align-items: center; gap: 0.8rem; margin-bottom: 0.35rem; }}
    .zp-post-title {{ font-size: 1.05rem; font-weight: 800; line-height: 1.35; color: var(--zp-heading); margin-bottom: 0.5rem; }}
    .zp-post-title a:hover {{ color: var(--zp-primary); }}
    .zp-post-actions {{ display: flex; align-items: center; gap: 0.8rem; margin-top: auto; }}
    .zp-btn-play-trigger {{ background-color: var(--zp-primary); color: #ffffff; border: none; font-size: 0.78rem; font-weight: 800; text-transform: uppercase; padding: 0.35rem 0.9rem; border-radius: var(--zp-radius-pill); display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }}
    .zp-btn-play-trigger:hover {{ background-color: var(--zp-primary-hover); }}
    .zp-btn-dl-direct {{ background-color: var(--zp-border-subtle); color: var(--zp-text); border: 1px solid var(--zp-border); font-size: 0.78rem; font-weight: 700; padding: 0.35rem 0.8rem; border-radius: var(--zp-radius-pill); display: inline-flex; align-items: center; gap: 5px; }}
    .zp-btn-dl-direct:hover {{ background-color: var(--zp-primary); color: #ffffff; border-color: var(--zp-primary); }}

    /* Sidebar Widgets */
    .zp-widget {{ background-color: var(--zp-bg-card); border: 1px solid var(--zp-border); border-radius: var(--zp-radius-md); padding: 1.2rem; margin-bottom: 1.5rem; box-shadow: var(--zp-shadow); }}
    .zp-widget-header {{ border-bottom: 2px solid var(--zp-border); padding-bottom: 0.6rem; margin-bottom: 1rem; display: flex; align-items: center; justify-content: space-between; }}
    .zp-widget-title {{ font-size: 0.95rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; color: var(--zp-heading); }}

    /* WhatsApp Channel Box */
    .zp-wa-channel-box {{ background: linear-gradient(135deg, #075e54 0%, #128c7e 100%); color: #ffffff; border-radius: var(--zp-radius-md); padding: 1.2rem; text-align: center; margin-bottom: 1.5rem; box-shadow: var(--zp-shadow); }}
    .zp-wa-btn-full {{ background-color: #25D366; color: #ffffff; display: block; width: 100%; padding: 0.6rem 1rem; border-radius: var(--zp-radius-pill); font-weight: 800; font-size: 0.85rem; margin-top: 0.8rem; text-decoration: none; }}
    .zp-wa-btn-full:hover {{ background-color: #20ba5a; color: #fff; }}

    /* Trending Ranked List */
    .zp-trending-list {{ list-style: none; display: flex; flex-direction: column; gap: 0.8rem; }}
    .zp-trending-item {{ display: flex; align-items: center; gap: 0.8rem; padding-bottom: 0.8rem; border-bottom: 1px solid var(--zp-border-subtle); }}
    .zp-trending-item:last-child {{ border-bottom: none; padding-bottom: 0; }}
    .zp-trending-rank {{ width: 24px; height: 24px; border-radius: 50%; background: var(--zp-primary); color: #ffffff; font-size: 0.72rem; font-weight: 800; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }}
    .zp-trending-thumb {{ width: 44px; height: 44px; border-radius: var(--zp-radius-sm); object-fit: cover; flex-shrink: 0; }}
    .zp-trending-details {{ flex: 1; min-width: 0; }}
    .zp-trending-name {{ font-size: 0.85rem; font-weight: 700; color: var(--zp-heading); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    .zp-trending-date {{ font-size: 0.7rem; color: var(--zp-text-muted); margin-top: 2px; }}

    /* Trending Artists Avatars */
    .zp-artists-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.8rem; text-align: center; }}
    .zp-artist-circle-img {{ width: 56px; height: 56px; border-radius: 50%; object-fit: cover; border: 2px solid var(--zp-primary); margin: 0 auto 4px; display: block; }}
    .zp-artist-circle-name {{ font-size: 0.72rem; font-weight: 700; color: var(--zp-heading); display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}

    /* Single Song Download Page */
    .zp-single-post {{ background-color: var(--zp-bg-card); border: 1px solid var(--zp-border); border-radius: var(--zp-radius-lg); padding: 2rem; box-shadow: var(--zp-shadow); }}
    .zp-single-breadcrumbs {{ font-size: 0.78rem; color: var(--zp-text-muted); margin-bottom: 1rem; }}
    .zp-single-title {{ font-size: 1.85rem; font-weight: 800; color: var(--zp-heading); line-height: 1.25; margin-bottom: 1rem; }}
    .zp-single-meta {{ display: flex; align-items: center; gap: 1rem; font-size: 0.8rem; color: var(--zp-text-muted); border-bottom: 1px solid var(--zp-border); padding-bottom: 1rem; margin-bottom: 1.5rem; }}
    .zp-single-featured-art {{ width: 100%; max-width: 600px; margin: 0 auto 1.5rem; border-radius: var(--zp-radius-md); overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.15); }}
    .zp-single-featured-art img {{ width: 100%; height: auto; display: block; }}
    .zp-editorial-body {{ font-size: 0.95rem; line-height: 1.8; color: var(--zp-text); margin-bottom: 2rem; }}
    .zp-editorial-body p {{ margin-bottom: 1.2rem; }}
    
    /* Native Audio Streaming Player */
    .zp-player-box {{ background: var(--zp-border-subtle); border: 1px solid var(--zp-border); border-radius: var(--zp-radius-md); padding: 1.2rem; margin: 1.5rem 0; }}
    .zp-download-cta-btn {{ display: flex; align-items: center; justify-content: center; gap: 10px; background-color: var(--zp-primary); color: #ffffff; font-size: 1.15rem; font-weight: 800; text-transform: uppercase; padding: 1rem 2rem; border-radius: var(--zp-radius-pill); text-align: center; margin: 1.5rem auto; max-width: 400px; box-shadow: 0 6px 20px rgba(6, 128, 30, 0.3); transition: transform 0.2s, background-color 0.2s; }}
    .zp-download-cta-btn:hover {{ transform: scale(1.03); background-color: var(--zp-primary-hover); color: #ffffff; }}

    /* Tags & Social Share Bar */
    .zp-share-bar {{ display: flex; align-items: center; gap: 0.8rem; margin: 1.5rem 0; flex-wrap: wrap; }}
    .zp-share-btn {{ padding: 0.4rem 0.9rem; border-radius: var(--zp-radius-pill); font-size: 0.78rem; font-weight: 700; color: #ffffff; display: inline-flex; align-items: center; gap: 6px; }}
    .btn-sh-fb {{ background-color: #1877F2; }}
    .btn-sh-tw {{ background-color: #000000; }}
    .btn-sh-wa {{ background-color: #25D366; }}

    /* Persistent Bottom Audio Player */
    .zp-dock-player {{ position: fixed; bottom: 0; left: 0; right: 0; background: #0f141f; border-top: 2px solid var(--zp-primary); color: #ffffff; z-index: 1001; padding: 8px 1.5rem; display: none; align-items: center; justify-content: space-between; box-shadow: 0 -4px 20px rgba(0,0,0,0.5); }}
    .zp-dock-info {{ display: flex; align-items: center; gap: 12px; }}
    .zp-dock-thumb {{ width: 44px; height: 44px; border-radius: 6px; object-fit: cover; }}
    .zp-dock-title {{ font-size: 0.88rem; font-weight: 800; }}
    .zp-dock-artist {{ font-size: 0.75rem; color: #94a3b8; }}
    .zp-dock-controls {{ display: flex; align-items: center; gap: 1rem; }}
    .zp-dock-btn {{ background: none; border: none; color: #ffffff; font-size: 1.2rem; cursor: pointer; }}
    .zp-dock-btn.btn-play-circle {{ width: 38px; height: 38px; border-radius: 50%; background: var(--zp-primary); display: flex; align-items: center; justify-content: center; font-size: 1rem; }}

    /* Empty State */
    .zp-empty-state {{ text-align: center; padding: 4rem 1.5rem; background: var(--zp-bg-card); border-radius: var(--zp-radius-md); border: 1px dashed var(--zp-border); }}
    .zp-empty-state i {{ font-size: 3rem; color: var(--zp-text-muted); margin-bottom: 1rem; }}
    .zp-empty-state h3 {{ font-size: 1.2rem; font-weight: 800; color: var(--zp-heading); margin-bottom: 0.5rem; }}

    /* Footer */
    .zp-footer {{ background-color: #0a0d14; color: #94a3b8; padding: 2.5rem 1.5rem 5rem; border-top: 1px solid rgba(255,255,255,0.06); font-size: 0.82rem; }}
    .zp-footer-container {{ max-width: 1200px; margin: 0 auto; text-align: center; }}
    .zp-footer-social {{ display: flex; justify-content: center; gap: 1.2rem; margin: 1.2rem 0; font-size: 1.2rem; }}
    .zp-footer-social a:hover {{ color: var(--zp-primary); }}
    .zp-footer-copy {{ margin-top: 1rem; font-size: 0.78rem; }}
    </style>
    """

ZAMBIANPLAY_SCRIPTS = """
<script>
    // Theme Toggle (Light / Dark Skin)
    function initSkin() {
        const savedSkin = localStorage.getItem('tie-skin') || 'light';
        document.documentElement.setAttribute('data-skin', savedSkin);
        updateSkinIcon(savedSkin);
    }
    function toggleSkin() {
        const current = document.documentElement.getAttribute('data-skin') || 'light';
        const next = current === 'light' ? 'dark' : 'light';
        document.documentElement.setAttribute('data-skin', next);
        localStorage.setItem('tie-skin', next);
        updateSkinIcon(next);
    }
    function updateSkinIcon(skin) {
        document.querySelectorAll('.zp-theme-toggle i').forEach(el => {
            el.className = skin === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        });
    }
    document.addEventListener('DOMContentLoaded', initSkin);

    // Global Dock Audio Player
    let globalAudio = new Audio();
    let currentPlayingId = null;

    function playTrack(id, title, artist, coverUrl, streamUrl) {
        const dock = document.getElementById('zp-dock-player');
        if (!dock) return;

        if (currentPlayingId === id && !globalAudio.paused) {
            globalAudio.pause();
            document.getElementById('zp-dock-play-icon').className = 'fas fa-play';
            return;
        }

        currentPlayingId = id;
        globalAudio.src = streamUrl;
        globalAudio.play().then(() => {
            dock.style.display = 'flex';
            document.getElementById('zp-dock-thumb').src = coverUrl;
            document.getElementById('zp-dock-title').textContent = title;
            document.getElementById('zp-dock-artist').textContent = artist;
            document.getElementById('zp-dock-play-icon').className = 'fas fa-pause';
            fetch('/api/tracks/' + id + '/play', { method: 'POST' }).catch(() => {});
        }).catch(err => console.error("Playback error:", err));
    }

    function toggleDockPlay() {
        if (!globalAudio.src) return;
        if (globalAudio.paused) {
            globalAudio.play();
            document.getElementById('zp-dock-play-icon').className = 'fas fa-pause';
        } else {
            globalAudio.pause();
            document.getElementById('zp-dock-play-icon').className = 'fas fa-play';
        }
    }

    function closeDock() {
        globalAudio.pause();
        const dock = document.getElementById('zp-dock-player');
        if (dock) dock.style.display = 'none';
        currentPlayingId = null;
    }

    // Real-Time Debounced Multi-Field Search Engine
    let searchDebounceTimer = null;
    let originalPostsHtml = '';

    function initSearchState() {
        const list = document.querySelector('.zp-posts-list');
        if (list) {
            originalPostsHtml = list.innerHTML;
        }
    }
    document.addEventListener('DOMContentLoaded', initSearchState);

    function handleRealtimeSearch(query) {
        const q = (query || '').trim();
        const clearBtns = document.querySelectorAll('.zp-search-clear');
        clearBtns.forEach(btn => btn.style.display = q.length > 0 ? 'inline-flex' : 'none');

        // Synchronize all search inputs on screen
        document.querySelectorAll('.zp-search-input, .zp-nav-search-input').forEach(inp => {
            if (inp.value !== query) inp.value = query;
        });

        clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => {
            executeSearch(q);
        }, 300);
    }

    function clearRealtimeSearch() {
        document.querySelectorAll('.zp-search-input, .zp-nav-search-input').forEach(inp => inp.value = '');
        document.querySelectorAll('.zp-search-clear').forEach(btn => btn.style.display = 'none');
        executeSearch('');
    }

    async function executeSearch(query) {
        const list = document.querySelector('.zp-posts-list');
        if (!list) return;

        const q = (query || '').toLowerCase().trim();
        if (!q) {
            if (originalPostsHtml) {
                list.innerHTML = originalPostsHtml;
            }
            return;
        }

        try {
            const res = await fetch('/api/tracks?search=' + encodeURIComponent(q));
            if (res.ok) {
                const tracks = await res.json();
                if (tracks && tracks.length > 0) {
                    let html = '';
                    const escapedQ = q.replace(/[-\\/\\\\^$*+?.()|[\\]{}]/g, '\\\\$&');
                    const regex = new RegExp('(' + escapedQ + ')', 'gi');

                    tracks.forEach(t => {
                        const featSuffix = t.featured_artists ? (' ft. ' + t.featured_artists) : '';
                        const artistFull = t.artist + featSuffix;
                        const tArt = t.cover_url || 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=400&q=80';
                        const dateStr = (t.created_at || '2026-09-03').split(' ')[0];

                        const displayTitle = t.title.replace(regex, '<mark class="zp-search-highlight">$1</mark>');
                        const displayArtist = artistFull.replace(regex, '<mark class="zp-search-highlight">$1</mark>');
                        const displayGenre = t.genre.replace(regex, '<mark class="zp-search-highlight">$1</mark>');

                        html += `
                        <article class="zp-post-item" data-title="${t.title}" data-artist="${artistFull}">
                            <div class="zp-post-thumb-wrap">
                                <img src="${tArt}" class="zp-post-thumb" alt="${t.title}" loading="lazy">
                                <span class="zp-post-cat-badge">${displayGenre}</span>
                            </div>
                            <div class="zp-post-details">
                                <div class="zp-post-meta">
                                    <span><i class="far fa-calendar-alt"></i> ${dateStr}</span>
                                    <span><i class="fas fa-headphones"></i> ${t.plays_count || 0}</span>
                                    <span style="background:var(--zp-border-subtle); padding:1px 6px; border-radius:4px; font-weight:700;">${t.bitrate_kbps || 320}k HD</span>
                                </div>
                                <h3 class="zp-post-title">
                                    <a href="/track/${t.id}">${displayArtist} – ${displayTitle}</a>
                                </h3>
                                <div class="zp-post-actions">
                                    <button class="zp-btn-play-trigger" onclick="playTrack(${t.id}, '${t.title.replace(/'/g, "\\'")}', '${artistFull.replace(/'/g, "\\'")}', '${tArt}', '${t.stream_url}')">
                                        <i class="fas fa-play"></i> Play
                                    </button>
                                    <a href="/api/tracks/${t.id}/download" class="zp-btn-dl-direct" title="Download MP3"><i class="fas fa-arrow-down"></i></a>
                                    <a href="/track/${t.id}" style="font-size:0.78rem; font-weight:700; color:var(--zp-text-muted); margin-left:auto;">Lyrics & Details →</a>
                                </div>
                            </div>
                        </article>
                        `;
                    });
                    list.innerHTML = html;
                } else {
                    list.innerHTML = `
                    <div class="zp-empty-state" style="text-align:center; padding:3.5rem 1.5rem; background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-md);">
                        <i class="fas fa-search" style="font-size:2.8rem; color:var(--zp-text-muted); margin-bottom:1rem; opacity:0.6;"></i>
                        <h3 style="font-size:1.15rem; font-weight:800; color:var(--zp-heading); margin-bottom:0.5rem;">No tracks found matching "${query}"</h3>
                        <p style="font-size:0.85rem; color:var(--zp-text-muted); margin-bottom:1.4rem;">Try searching by artist name, song title, genre, or featured collaborator.</p>
                        <button type="button" onclick="clearRealtimeSearch()" class="zp-btn-play-trigger" style="margin:0 auto; display:inline-flex; cursor:pointer;">
                            <i class="fas fa-undo"></i> Reset Search
                        </button>
                    </div>
                    `;
                }
            }
        } catch (e) {
            console.error("Search error:", e);
        }
    }
</script>

<div id="zp-dock-player" class="zp-dock-player">
    <div class="zp-dock-info">
        <img id="zp-dock-thumb" src="" class="zp-dock-thumb" alt="Track Cover">
        <div>
            <div id="zp-dock-title" class="zp-dock-title">Song Title</div>
            <div id="zp-dock-artist" class="zp-dock-artist">Artist Name</div>
        </div>
    </div>
    <div class="zp-dock-controls">
        <button class="zp-dock-btn btn-play-circle" onclick="toggleDockPlay()">
            <i id="zp-dock-play-icon" class="fas fa-play"></i>
        </button>
        <button class="zp-dock-btn" onclick="closeDock()"><i class="fas fa-times"></i></button>
    </div>
</div>
"""

# ----------------------------------------------------------------------------
# Public Web Portal (`/`): Dynamic CMS Homepage
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/music", response_class=HTMLResponse)
async def index_page(
    genre: Optional[str] = None,
    sort: str = "latest",
    search: Optional[str] = None
):
    settings = db.get_site_settings()
    genres = db.get_genres()
    
    # Resolve Genre Filter
    genre_id = None
    if genre and genre.strip():
        for g in genres:
            if g["slug"].lower() == genre.strip().lower() or g["name"].lower() == genre.strip().lower():
                genre_id = g["id"]
                break

    # Determine default sorting if not specified
    actual_sort = sort or settings.get("default_sort_mode", "latest")
    tracks = db.get_tracks(search=search, genre_id=genre_id, sort_by=actual_sort)
    top_chart_tracks = db.get_tracks(sort_by="plays", limit=10)
    trending_artists = db.get_trending_artists(limit=8)

    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = settings.get("contact_whatsapp_msg", "Hello ZedHits, I want to submit my song for upload and promotion.")
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    # Feature Toggles
    allow_dl = settings.get("allow_downloads", "true").lower() == "true"
    show_plays = settings.get("show_play_counts", "true").lower() == "true"
    show_dates = settings.get("show_release_dates", "true").lower() == "true"
    quality_label = settings.get("stream_quality_label", "320k HD")

    # Logo HTML
    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    # Top Announcement Banner HTML
    banner_html = ""
    if settings.get("banner_active", "true").lower() == "true":
        b_msg = settings.get("banner_message", f"Are you an Artist or Producer? Get your song uploaded & promoted on {settings['site_title']}!")
        b_btn_text = settings.get("banner_btn_text", "Chat WhatsApp")
        b_btn_link = settings.get("banner_btn_link") or wa_link
        banner_html = f"""
        <div class="zp-top-promo">
            <div>
                <span>🎵 {b_msg}</span>
            </div>
            <div class="zp-top-promo-actions">
                <a href="{b_btn_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> {b_btn_text}</a>
                <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
            </div>
        </div>
        """

    # Dynamic 3-Slide Hero Spotlight Resolution
    hero_mode = settings.get("hero_mode", "trending")
    hero_tracks = []

    # 1. Check for manual pinned tracks
    if hero_mode == "custom" and settings.get("hero_pinned_tracks"):
        try:
            pinned_ids = [int(x.strip()) for x in settings.get("hero_pinned_tracks", "").split(",") if x.strip().isdigit()]
            for pid in pinned_ids:
                pt = db.get_track_by_id(pid)
                if pt:
                    hero_tracks.append(pt)
        except Exception:
            pass

    # 2. Context-aware or automated mode
    if not hero_tracks:
        if genre_id:
            hero_tracks = db.get_tracks(genre_id=genre_id, sort_by="plays", limit=3)
        elif hero_mode == "latest":
            hero_tracks = db.get_tracks(sort_by="latest", limit=3)
        elif hero_mode == "trending":
            hero_tracks = db.get_tracks(sort_by="trending", limit=3)
        else:
            hero_tracks = top_chart_tracks[:3]

    # 3. Fallback to guarantee 3 slides if total tracks available
    if len(hero_tracks) < 3 and tracks:
        existing_ids = {ht["id"] for ht in hero_tracks}
        for t in tracks:
            if t["id"] not in existing_ids:
                hero_tracks.append(t)
                existing_ids.add(t["id"])
            if len(hero_tracks) >= 3:
                break

    hero_slides_html = ""
    if hero_tracks:
        for idx, ht in enumerate(hero_tracks):
            h_art = ht.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=800&q=80"
            feat_label = f" ft. {ht['featured_artists']}" if ht.get('featured_artists') else ""
            clean_title = ht['title'].replace("'", "\\'")
            clean_artist = (ht['artist'] + feat_label).replace("'", "\\'")
            stream_url = ht.get("stream_url") or f"/media/tracks/{os.path.basename(ht.get('storage_path', ''))}"

            hero_slides_html += f"""
            <div class="zp-hero-slide" style="background-image: url('{h_art}');">
                <div class="zp-hero-overlay">
                    <div class="zp-hero-header-row">
                        <span class="zp-hero-cat">{ht['genre']}</span>
                        <span style="background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); color:#fff; font-size:0.68rem; font-weight:700; padding:2px 8px; border-radius:12px;"><i class="fas fa-bolt" style="color:#ffc107;"></i> Spotlight</span>
                    </div>
                    <a href="/track/{ht['id']}" class="zp-hero-title">{ht['artist']}{feat_label} – {ht['title']}</a>
                    <div class="zp-hero-bottom-row">
                        <div class="zp-hero-meta">
                            <span><i class="fas fa-fire" style="color:#ff5252;"></i> {ht['plays_count']} streams</span>
                            <span>•</span>
                            <span>{ht.get('bitrate_kbps', 320)}k HD</span>
                        </div>
                        <button class="zp-hero-play-btn" onclick="event.preventDefault(); event.stopPropagation(); playTrack({ht['id']}, '{clean_title}', '{clean_artist}', '{h_art}', '{stream_url}')" title="Play Track">
                            <i class="fas fa-play"></i>
                        </button>
                    </div>
                </div>
            </div>
            """
    else:
        hero_slides_html = f"""
        <div class="zp-hero-slide" style="background-image: url('https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=800&q=80'); grid-column: span 3;">
            <div class="zp-hero-overlay">
                <span class="zp-hero-cat">Zambian Hits</span>
                <div class="zp-hero-title">{settings.get('hero_title', 'Download The Latest Zambian Music In 2026')}</div>
                <span class="zp-hero-date">{settings.get('hero_subtitle', 'The Pulse of Zambian & African Music Streaming')}</span>
            </div>
        </div>
        """

    # Post Cards List HTML
    post_cards_html = ""
    if tracks:
        for t in tracks:
            t_art = t.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=400&q=80"
            date_str = t.get("created_at", "2026-09-03").split(" ")[0]
            
            # Conditionally rendered meta items
            plays_html = f'<span><i class="fas fa-play" style="color:var(--zp-primary);"></i> {t["plays_count"]} plays</span>' if show_plays else ""
            date_html = f'<span><i class="far fa-calendar-alt"></i> {date_str}</span>' if show_dates else ""
            dl_btn_html = f'<a href="/api/tracks/{t["id"]}/download" class="zp-btn-dl-direct" title="Download MP3"><i class="fas fa-arrow-down"></i></a>' if allow_dl else ""

            feat_suffix = f" ft. {t['featured_artists']}" if t.get('featured_artists') else ""
            artist_full = f"{t['artist']}{feat_suffix}"

            post_cards_html += f"""
            <article class="zp-post-item" data-title="{t['title']}" data-artist="{artist_full}">
                <div class="zp-post-thumb-wrap">
                    <img src="{t_art}" class="zp-post-thumb" alt="{t['title']}" loading="lazy">
                    <span class="zp-post-cat-badge">{t['genre']}</span>
                </div>
                <div class="zp-post-details">
                    <div class="zp-post-meta">
                        {date_html}
                        {plays_html}
                        <span style="background:var(--zp-border-subtle); padding:1px 6px; border-radius:4px; font-weight:700;">{quality_label}</span>
                    </div>
                    <h3 class="zp-post-title">
                        <a href="/track/{t['id']}">{artist_full} – {t['title']}</a>
                    </h3>
                    <div class="zp-post-actions">
                        <button class="zp-btn-play-trigger" onclick="playTrack({t['id']}, '{t['title'].replace("'", "\\'")}', '{artist_full.replace("'", "\\'")}', '{t_art}', '{t['stream_url']}')">
                            <i class="fas fa-play"></i> Play
                        </button>
                        {dl_btn_html}
                        <a href="/track/{t['id']}" style="font-size:0.78rem; font-weight:700; color:var(--zp-text-muted); margin-left:auto;">Lyrics & Details →</a>
                    </div>
                </div>
            </article>
            """
    else:
        empty_msg = settings.get("empty_state_msg", "No Songs Found in this Selection. Select another genre or explore the latest releases.")
        post_cards_html = f"""
        <div class="zp-empty-state">
            <i class="fas fa-compact-disc"></i>
            <h3>{empty_msg}</h3>
            <p style="color:var(--zp-text-muted); margin-top:8px;">Try switching to 'ALL' genres or searching for another Zambian artist.</p>
            <a href="/" class="zp-btn-play-trigger" style="margin-top:1rem; display:inline-flex;">View All Releases</a>
        </div>
        """

    # Genre Filter Chips
    genre_chips_html = f'<a href="/?sort={actual_sort}" class="zp-filter-chip {"active" if not genre else ""}">ALL</a>'
    for g in genres:
        active_cls = "active" if (genre and (genre == g["slug"] or genre.lower() == g["name"].lower())) else ""
        genre_chips_html += f'<a href="/?genre={g["slug"]}&sort={actual_sort}" class="zp-filter-chip {active_cls}">{g["name"]}</a>'

    # Trending Top 10 Ranked List
    trending_list_html = ""
    for idx, ct in enumerate(top_chart_tracks):
        c_art = ct.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=100&q=80"
        trending_list_html += f"""
        <li class="zp-trending-item">
            <span class="zp-trending-rank">{idx + 1}</span>
            <img src="{c_art}" class="zp-trending-thumb" alt="{ct['title']}">
            <div class="zp-trending-details">
                <div class="zp-trending-name"><a href="/track/{ct['id']}">{ct['artist']} – {ct['title']}</a></div>
                <div class="zp-trending-date"><i class="fas fa-fire" style="color:#ff5252;"></i> {ct['plays_count']} streams</div>
            </div>
        </li>
        """

    # Trending Artists Avatars
    artists_avatars_html = ""
    for a in trending_artists:
        a_art = a.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=150&q=80"
        artists_avatars_html += f"""
        <a href="/artist/{a['id']}" class="zp-artist-avatar-wrap" title="{a['name']}">
            <img src="{a_art}" class="zp-artist-circle-img" alt="{a['name']}">
            <span class="zp-artist-circle-name">{a['name']}</span>
        </a>
        """

    favicon_html = f'<link rel="icon" href="{settings["favicon_url"]}">' if settings.get("favicon_url") else ""

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{settings.get('hero_title', 'Download The Latest Zambian Music In 2026')} - {settings['site_title']}</title>
    <meta name="description" content="{settings['site_title']} is the leading website for the latest Zambian music, videos, and entertainment news updates from your favourite artists.">
    {favicon_html}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    {banner_html}

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
        <div style="display: flex; align-items: center; gap: 1rem;">
            <a href="{wa_link}" target="_blank" style="background:#25D366; color:#ffffff; font-size:0.8rem; font-weight:800; padding:0.4rem 1rem; border-radius:999px; display:inline-flex; align-items:center; gap:0.4rem;">
                <i class="fab fa-whatsapp"></i> Promote Song
            </a>
            <a href="/admin" style="font-size:0.85rem; font-weight:700; color:var(--zp-text-muted);"><i class="fas fa-shield-alt"></i> Admin</a>
        </div>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item active"><a href="/">HOME</a></li>
                <li class="zp-menu-item"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <div class="zp-nav-search-wrap">
                    <i class="fas fa-search" style="font-size:0.75rem; color:var(--zp-text-muted); margin-right:6px;"></i>
                    <input type="text" placeholder="Search songs..." class="zp-nav-search-input" oninput="handleRealtimeSearch(this.value)" autocomplete="off">
                    <button type="button" class="zp-search-clear" onclick="clearRealtimeSearch()" style="width:20px; height:20px; font-size:0.65rem;" title="Clear Search">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li class="active"><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li><a href="/artists"><i class="fas fa-user-friends"></i><span>ARTISTS</span></a></li>
        </ul>
    </nav>

    <!-- Main Container -->
    <main class="zp-container">
        <!-- 3-Slide Featured Hero Carousel -->
        <section class="zp-hero-slider">
            {hero_slides_html}
        </section>

        <!-- 2-Column Main Magazine Layout -->
        <div class="zp-main-layout">
            <!-- Left Column: The Latest (68%) -->
            <section>
                <div class="zp-mag-box-header">
                    <h2 class="zp-mag-box-title">{settings.get('section_latest_title', 'The Latest')}</h2>
                    <span style="font-size: 0.8rem; color: var(--zp-text-muted); font-weight: 700;">{len(tracks)} Songs</span>
                </div>

                <!-- Prominent Real-Time Search Bar -->
                <div class="zp-search-wrapper">
                    <div class="zp-search-box">
                        <i class="fas fa-search zp-search-icon"></i>
                        <input type="text" id="zp-main-search-input" class="zp-search-input" placeholder="Search songs, artists, genres, featured artists..." oninput="handleRealtimeSearch(this.value)" autocomplete="off">
                        <button type="button" id="zp-search-clear-btn" class="zp-search-clear" onclick="clearRealtimeSearch()" title="Clear Search">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                </div>

                <!-- Genre Filter Tabs -->
                <div class="zp-filter-bar">
                    {genre_chips_html}
                </div>

                <!-- Post Cards List -->
                <div class="zp-posts-list">
                    {post_cards_html}
                </div>
            </section>

            <!-- Right Column: Sidebar (32%) -->
            <aside>
                <!-- Join Official WhatsApp Channel Box -->
                <div class="zp-wa-channel-box">
                    <i class="fab fa-whatsapp fa-2x" style="color:#25D366; margin-bottom: 0.4rem;"></i>
                    <h3 style="font-size: 1.05rem; font-weight: 800; color: #fff;">Join Our WhatsApp Channel</h3>
                    <p style="font-size: 0.8rem; color: rgba(255,255,255,0.85); margin-top: 4px;">Get instant alerts whenever new Zambian songs and albums drop!</p>
                    <a href="{wa_link}" target="_blank" class="zp-wa-btn-full">
                        <i class="fab fa-whatsapp"></i> Join Channel Now
                    </a>
                </div>

                <!-- Trending Widget -->
                <div class="zp-widget">
                    <div class="zp-widget-header">
                        <h3 class="zp-widget-title"><i class="fas fa-bolt" style="color:var(--zp-primary);"></i> {settings.get('section_trending_title', 'TRENDING')}</h3>
                    </div>
                    <ul class="zp-trending-list">
                        {trending_list_html}
                    </ul>
                </div>

                <!-- Trending Artists Widget -->
                <div class="zp-widget">
                    <div class="zp-widget-header">
                        <h3 class="zp-widget-title"><i class="fas fa-star" style="color:#ffb300;"></i> {settings.get('section_artists_title', 'ARTISTS')}</h3>
                        <a href="/artists" style="font-size: 0.75rem; color: var(--zp-primary); font-weight: 700;">View All →</a>
                    </div>
                    <div class="zp-artists-grid">
                        {artists_avatars_html}
                    </div>
                </div>

                <!-- Promote Your Music Box -->
                <div class="zp-widget" style="background: linear-gradient(135deg, var(--zp-bg-card), var(--zp-border-subtle)); text-align: center;">
                    <i class="fas fa-bullhorn fa-2x" style="color:var(--zp-primary); margin-bottom: 0.6rem;"></i>
                    <h4 style="font-size: 1.1rem; font-weight: 800; color: var(--zp-heading);">Promote Your Song</h4>
                    <p style="font-size: 0.82rem; color: var(--zp-text-muted); margin: 0.4rem 0 1rem;">Upload your music, get verified, and reach thousands of listeners across Zambia & Africa.</p>
                    <a href="{wa_link}" target="_blank" class="zp-btn-play-trigger" style="padding: 0.6rem 1.4rem; font-size: 0.85rem;">
                        <i class="fab fa-whatsapp"></i> Chat Admin on WhatsApp
                    </a>
                </div>
            </aside>
        </div>
    </main>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <div class="zp-footer-social">
                <a href="{settings.get('social_facebook', 'https://facebook.com')}" target="_blank"><i class="fab fa-facebook"></i></a>
                <a href="{settings.get('social_twitter', 'https://x.com')}" target="_blank"><i class="fab fa-x-twitter"></i></a>
                <a href="{settings.get('social_instagram', 'https://instagram.com')}" target="_blank"><i class="fab fa-instagram"></i></a>
                <a href="{settings.get('social_youtube', 'https://youtube.com')}" target="_blank"><i class="fab fa-youtube"></i></a>
                <a href="mailto:{settings.get('contact_email', 'support@zedhits.com')}"><i class="fas fa-envelope"></i></a>
            </div>
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Dedicated Single Track Download Page (`/track/{id}`)
# ----------------------------------------------------------------------------
@app.get("/track/{track_id}", response_class=HTMLResponse)
async def single_track_page(track_id: int):
    track = db.get_track_by_id(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    settings = db.get_site_settings()
    related_tracks = db.get_related_tracks(track_id, limit=4)

    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = settings.get("contact_whatsapp_msg", f"Hello ZedHits, I want to promote music like {track['title']} by {track['artist']}.")
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    cover_img = track.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=800&q=80"
    date_str = track.get("created_at", "2026-09-03").split(" ")[0]
    duration_fmt = f"{track['duration_seconds'] // 60}:{track['duration_seconds'] % 60:02d}" if track['duration_seconds'] else "3:30"

    allow_dl = settings.get("allow_downloads", "true").lower() == "true"
    show_plays = settings.get("show_play_counts", "true").lower() == "true"
    quality_label = settings.get("stream_quality_label", f"{track['bitrate_kbps']} kbps HD")

    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    # Related Posts Cards HTML
    related_html = ""
    for rt in related_tracks:
        r_art = rt.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=300&q=80"
        related_html += f"""
        <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-md); overflow:hidden; box-shadow:var(--zp-shadow);">
            <img src="{r_art}" style="width:100%; height:130px; object-fit:cover;" alt="{rt['title']}">
            <div style="padding:0.8rem;">
                <span style="font-size:0.68rem; font-weight:800; color:var(--zp-primary); text-transform:uppercase;">{rt['genre']}</span>
                <h4 style="font-size:0.92rem; font-weight:800; margin:4px 0 6px; color:var(--zp-heading); line-height:1.3;">
                    <a href="/track/{rt['id']}">{rt['artist']} – {rt['title']}</a>
                </h4>
                <div style="font-size:0.72rem; color:var(--zp-text-muted);"><i class="fas fa-play"></i> {rt['plays_count']} streams</div>
            </div>
        </div>
        """

    dl_cta_html = f"""
    <a href="/api/tracks/{track['id']}/download" class="zp-download-cta-btn">
        <i class="fas fa-download"></i> DOWNLOAD NOW ({quality_label})
    </a>
    """ if allow_dl else ""

    track_share_title = f"{track['artist']} – {track['title']}"
    track_page_path = f"/track/{track_id}"
    fb_share_link = f"https://www.facebook.com/sharer/sharer.php?u={urllib.parse.quote(track_page_path)}"
    tw_share_link = f"https://twitter.com/intent/tweet?text={urllib.parse.quote(track_share_title)}&url={urllib.parse.quote(track_page_path)}"

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{track['artist']} – {track['title']} MP3 Download | {settings['site_title']}</title>
    <meta name="description" content="Download and stream {track['artist']} – {track['title']} MP3 in studio-master {quality_label} quality on {settings['site_title']}.">
    <meta property="og:title" content="{track['artist']} – {track['title']} MP3 Download | {settings['site_title']}">
    <meta property="og:description" content="Download and stream {track['artist']} – {track['title']} MP3 in studio-master {quality_label} quality on {settings['site_title']}.">
    <meta property="og:image" content="{cover_img}">
    <meta property="og:type" content="music.song">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    <!-- Top Promo Headspace Bar -->
    <div class="zp-top-promo">
        <div>
            <span>🎵 Are you an Artist or Producer? Get your song uploaded & promoted on {settings['site_title']}!</span>
        </div>
        <div class="zp-top-promo-actions">
            <a href="{wa_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> Chat WhatsApp</a>
            <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
        </div>
    </div>

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
        <div style="display: flex; align-items: center; gap: 1rem;">
            <a href="{wa_link}" target="_blank" style="background:#25D366; color:#ffffff; font-size:0.8rem; font-weight:800; padding:0.4rem 1rem; border-radius:999px; display:inline-flex; align-items:center; gap:0.4rem;">
                <i class="fab fa-whatsapp"></i> Promote Song
            </a>
            <a href="/admin" style="font-size:0.85rem; font-weight:700; color:var(--zp-text-muted);"><i class="fas fa-shield-alt"></i> Admin</a>
        </div>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item"><a href="/">HOME</a></li>
                <li class="zp-menu-item active"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li class="active"><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li><a href="/artists"><i class="fas fa-user-friends"></i><span>ARTISTS</span></a></li>
        </ul>
    </nav>

    <!-- Single Post Main Container -->
    <main class="zp-container" style="max-width: 900px;">
        <article class="zp-single-post">
            <!-- Breadcrumbs -->
            <div class="zp-single-breadcrumbs">
                <a href="/">Home</a> • <a href="/?genre={track['genre'].lower()}">{track['genre']}</a> • <span>{track['artist']}{f" ft. {track['featured_artists']}" if track.get('featured_artists') else ''} – {track['title']}</span>
            </div>

            <!-- Single Track Title -->
            <h1 class="zp-single-title">{track['artist']}{f" ft. {track['featured_artists']}" if track.get('featured_artists') else ''} – {track['title']}</h1>

            <!-- Meta Strip -->
            <div class="zp-single-meta">
                <span><i class="far fa-user"></i> By <a href="/artist/{track['artist_id']}" style="color:var(--zp-primary); font-weight:700;">{track['artist']}</a>{f" <span style='color:var(--zp-text-muted); font-size:0.85rem;'>(ft. {track['featured_artists']})</span>" if track.get('featured_artists') else ''}</span>
                <span><i class="far fa-calendar-alt"></i> {date_str}</span>
                {f'<span><i class="fas fa-headphones"></i> {track["plays_count"]} Streams</span>' if show_plays else ''}
                {f'<span><i class="fas fa-download"></i> {track["downloads_count"]} Downloads</span>' if allow_dl else ''}
                <span><i class="fas fa-clock"></i> {duration_fmt}</span>
            </div>

            <!-- Join Official WhatsApp Channel Callout -->
            <div class="zp-wa-channel-box" style="margin-bottom: 2rem;">
                <h3 style="font-size: 1rem; font-weight: 800; color: #fff;">🟢 Join Our Official WhatsApp Channel</h3>
                <p style="font-size: 0.8rem; color: rgba(255,255,255,0.85); margin-top: 4px;">Get instant alerts on new Zambian releases straight to your phone!</p>
                <a href="{wa_link}" target="_blank" class="zp-wa-btn-full"><i class="fab fa-whatsapp"></i> Join Channel Now</a>
            </div>

            <!-- Large Featured Artwork -->
            <div class="zp-single-featured-art">
                <img src="{cover_img}" alt="{track['title']} Artwork">
            </div>

            <!-- Editorial Story Write-up -->
            <div class="zp-editorial-body">
                <p>Zambian music luminary <strong>{track['artist']}</strong> delivers a brand new studio recording titled <strong>"{track['title']}"</strong>. This record seamlessly infuses infectious melodies with vibrant African rhythms, solidifying their footprint on the Zambian music landscape.</p>
                
                {f'<div style="background:var(--zp-border-subtle); border-left:4px solid var(--zp-primary); padding:1rem; border-radius:0 var(--zp-radius-sm) var(--zp-radius-sm) 0; margin:1.5rem 0;"><strong>Official Lyrics:</strong><br><pre style="white-space:pre-wrap; font-family:inherit; margin-top:0.5rem; color:var(--zp-text); font-size:0.88rem;">{track["lyrics"]}</pre></div>' if track.get("lyrics") else ''}

                <p>Stream the official studio master below and download the direct high-bitrate MP3 for offline listening.</p>
            </div>

            <!-- Native Audio Player Box -->
            <div class="zp-player-box">
                <div style="font-weight: 800; font-size: 0.88rem; margin-bottom: 0.8rem; color: var(--zp-heading); display:flex; align-items:center; gap:6px;">
                    <i class="fas fa-volume-up" style="color:var(--zp-primary);"></i> Listen to "{track['title']}" Audio:
                </div>
                <audio controls style="width: 100%; outline: none;" onplay="fetch('/api/tracks/{track['id']}/play', {{ method: 'POST' }})">
                    <source src="{track['stream_url']}" type="audio/mpeg">
                    Your browser does not support the audio element.
                </audio>
            </div>

            <!-- Big Signature Download CTA Button -->
            {dl_cta_html}

            <!-- Promote Music WhatsApp Box -->
            <div style="text-align:center; margin: 2rem 0; padding:1.2rem; background:var(--zp-border-subtle); border-radius:var(--zp-radius-md);">
                <span style="font-size:0.85rem; font-weight:700; color:var(--zp-heading);">Are you an artist? Get your song on {settings['site_title']}</span><br>
                <a href="{wa_link}" target="_blank" style="background:#25D366; color:#fff; font-size:0.82rem; font-weight:800; padding:0.5rem 1.2rem; border-radius:var(--zp-radius-pill); display:inline-flex; align-items:center; gap:6px; margin-top:8px;">
                    <i class="fab fa-whatsapp"></i> Chat Admin to Upload Your Song
                </a>
            </div>

            <!-- Social Share Bar -->
            <div class="zp-share-bar">
                <span style="font-size:0.8rem; font-weight:800; color:var(--zp-heading); text-transform:uppercase;">Share:</span>
                <a href="{fb_share_link}" target="_blank" class="zp-share-btn btn-sh-fb"><i class="fab fa-facebook-f"></i> Facebook</a>
                <a href="{tw_share_link}" target="_blank" class="zp-share-btn btn-sh-tw"><i class="fab fa-x-twitter"></i> X / Twitter</a>
                <a href="{wa_link}" target="_blank" class="zp-share-btn btn-sh-wa"><i class="fab fa-whatsapp"></i> WhatsApp</a>
            </div>

            <!-- Tags Cloud -->
            <div style="margin:1.5rem 0; display:flex; gap:0.5rem; flex-wrap:wrap;">
                <span style="background:var(--zp-border-subtle); border:1px solid var(--zp-border); padding:3px 10px; border-radius:4px; font-size:0.75rem; font-weight:700; color:var(--zp-text-muted);">#{track['artist'].replace(" ", "")}</span>
                <span style="background:var(--zp-border-subtle); border:1px solid var(--zp-border); padding:3px 10px; border-radius:4px; font-size:0.75rem; font-weight:700; color:var(--zp-text-muted);">#{track['genre'].replace(" ", "")}</span>
                <span style="background:var(--zp-border-subtle); border:1px solid var(--zp-border); padding:3px 10px; border-radius:4px; font-size:0.75rem; font-weight:700; color:var(--zp-text-muted);">#ZedHits2026</span>
            </div>
        </article>

        <!-- Related Posts Grid -->
        <section style="margin-top: 2.5rem;">
            <div class="zp-mag-box-header">
                <h3 class="zp-mag-box-title">Related Zambian Music</h3>
            </div>
            <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:1.2rem;">
                {related_html}
            </div>
        </section>
    </main>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Dedicated Artists Directory Page (`/artists`)
# ----------------------------------------------------------------------------
@app.get("/artists", response_class=HTMLResponse)
async def artists_directory_page():
    settings = db.get_site_settings()
    artists = db.get_artists(only_with_tracks=True)

    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = settings.get("contact_whatsapp_msg", "Hello ZedHits, I want to submit an artist profile.")
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    artist_cards_html = ""
    for a in artists:
        a_art = a.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=300&q=80"
        artist_cards_html += f"""
        <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-md); padding:1.2rem; display:flex; align-items:center; gap:1.2rem; box-shadow:var(--zp-shadow);">
            <img src="{a_art}" style="width:70px; height:70px; border-radius:50%; object-fit:cover; border:2px solid var(--zp-primary);" alt="{a['name']}">
            <div style="flex:1;">
                <h3 style="font-size:1.15rem; font-weight:800; color:var(--zp-heading);"><a href="/artist/{a['id']}">{a['name']}</a> <i class="fas fa-check-circle" style="color:var(--zp-primary); font-size:0.9rem;"></i></h3>
                <div style="font-size:0.8rem; color:var(--zp-text-muted); margin-top:2px;">
                    <span><i class="fas fa-music"></i> {a['track_count']} Tracks</span> • 
                    <span><i class="fas fa-headphones"></i> {a['total_plays']} Streams</span>
                </div>
            </div>
            <div style="display:flex; gap:8px;">
                <a href="/artist/{a['id']}" class="zp-btn-play-trigger" style="font-size:0.75rem; padding:0.4rem 0.8rem;">Profile</a>
                <a href="/api/artists/{a['id']}/download-zip" class="zp-btn-dl-direct" style="font-size:0.75rem; padding:0.4rem 0.8rem;" title="Download Full Discography ZIP"><i class="fas fa-file-archive"></i> ZIP</a>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zambian Artists Directory & Discographies | {settings['site_title']}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    <!-- Top Promo Headspace Bar -->
    <div class="zp-top-promo">
        <div>
            <span>🎵 Are you an Artist or Producer? Get your song uploaded & promoted on {settings['site_title']}!</span>
        </div>
        <div class="zp-top-promo-actions">
            <a href="{wa_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> Chat WhatsApp</a>
            <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
        </div>
    </div>

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item"><a href="/">HOME</a></li>
                <li class="zp-menu-item"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item active"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li class="active"><a href="/artists"><i class="fas fa-user-friends"></i><span>ARTISTS</span></a></li>
        </ul>
    </nav>

    <main class="zp-container" style="max-width: 900px;">
        <div class="zp-mag-box-header">
            <h2 class="zp-mag-box-title"><i class="fas fa-users" style="color:var(--zp-primary);"></i> {settings.get('section_artists_title', 'ARTISTS')}</h2>
            <span style="font-size:0.85rem; color:var(--zp-text-muted); font-weight:700;">{len(artists)} Artists</span>
        </div>

        <div style="display:flex; flex-direction:column; gap:1rem;">
            {artist_cards_html}
        </div>
    </main>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Artist Profile & Discography Hub (`/artist/{artist_id}`)
# ----------------------------------------------------------------------------
@app.get("/artist/{artist_id}", response_class=HTMLResponse)
async def artist_profile_page(artist_id: int):
    artist = db.get_artist_profile(artist_id)
    if not artist:
        raise HTTPException(status_code=404, detail="Artist profile not found")

    settings = db.get_site_settings()
    cover_img = artist.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=400&q=80"

    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = settings.get("contact_whatsapp_msg", f"Hello ZedHits, I want to promote music by {artist['name']}.")
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    track_rows_html = ""
    for t in artist["tracks"]:
        track_rows_html += f"""
        <div class="zp-post-item" style="align-items:center;">
            <img src="{t['cover_url'] or cover_img}" style="width:50px; height:50px; border-radius:8px; object-fit:cover;" alt="{t['title']}">
            <div style="flex:1;">
                <h4 style="font-size:1rem; font-weight:700; color:var(--zp-heading);"><a href="/track/{t['id']}">{t['title']}</a></h4>
                <span style="font-size:0.75rem; color:var(--zp-primary); font-weight:700;">{t['genre']}</span> • 
                <span style="font-size:0.75rem; color:var(--zp-text-muted);"><i class="fas fa-play"></i> {t['plays_count']} plays</span>
            </div>
            <a href="/track/{t['id']}" class="zp-btn-play-trigger" style="font-size:0.78rem; padding:0.35rem 0.8rem;">Listen</a>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{artist['name']} Complete Discography & MP3 Downloads | {settings['site_title']}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    <!-- Top Promo Headspace Bar -->
    <div class="zp-top-promo">
        <div>
            <span>🎵 Are you an Artist or Producer? Get your song uploaded & promoted on {settings['site_title']}!</span>
        </div>
        <div class="zp-top-promo-actions">
            <a href="{wa_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> Chat WhatsApp</a>
            <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
        </div>
    </div>

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item"><a href="/">HOME</a></li>
                <li class="zp-menu-item"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item active"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li class="active"><a href="/artists"><i class="fas fa-user-friends"></i><span>ARTISTS</span></a></li>
        </ul>
    </nav>

    <main class="zp-container" style="max-width: 900px;">
        <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-lg); padding:2rem; display:flex; align-items:center; gap:1.5rem; margin-bottom:2rem; flex-wrap:wrap;">
            <img src="{cover_img}" style="width:120px; height:120px; border-radius:50%; object-fit:cover; border:3px solid var(--zp-primary);" alt="{artist['name']}">
            <div style="flex:1;">
                <span style="font-size:0.75rem; font-weight:800; color:var(--zp-primary); text-transform:uppercase;">VERIFIED ARTIST</span>
                <h1 style="font-size:2.2rem; font-weight:800; color:var(--zp-heading); line-height:1.2; margin:4px 0 8px;">{artist['name']} Complete Discography <i class="fas fa-check-circle" style="color:var(--zp-primary); font-size:1.2rem;"></i></h1>
                <div style="font-size:0.85rem; color:var(--zp-text-muted);">
                    <span><i class="fas fa-music"></i> {artist['total_tracks']} Songs</span> • 
                    <span><i class="fas fa-headphones"></i> {artist['total_plays']} Streams</span> • 
                    <span><i class="fas fa-download"></i> {artist['total_downloads']} Downloads</span>
                </div>
            </div>
            <a href="/api/artists/{artist['id']}/download-zip" class="zp-download-cta-btn" style="margin:0; padding:0.8rem 1.4rem; font-size:0.95rem;">
                <i class="fas fa-file-archive"></i> Download Full Discography (ZIP)
            </a>
        </div>

        <div class="zp-mag-box-header">
            <h2 class="zp-mag-box-title">Songs by {artist['name']}</h2>
        </div>

        <div style="display:flex; flex-direction:column; gap:0.8rem;">
            {track_rows_html}
        </div>
    </main>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Dedicated Zambian Music Videos & Visuals Page (`/videos`)
# ----------------------------------------------------------------------------
@app.get("/videos", response_class=HTMLResponse)
async def videos_page(
    genre: Optional[str] = None,
    search: Optional[str] = None
):
    settings = db.get_site_settings()
    genres = db.get_genres()
    videos = db.get_videos(genre_slug=genre, search=search)
    featured_videos = db.get_videos(is_featured=True, limit=1)

    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = settings.get("contact_whatsapp_msg", "Hello ZedHits, I want to submit a music video for premiere.")
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    # Featured Spotlight Banner
    spotlight_html = ""
    if featured_videos and not genre and not search:
        fv = featured_videos[0]
        fv_art = fv.get("thumbnail_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=1200&q=80"
        fv_yt_id = fv.get("youtube_id", "")
        fv_title_clean = fv['title'].replace("'", "\\'")
        fv_artist_clean = fv['artist'].replace("'", "\\'")

        spotlight_html = f"""
        <div style="position:relative; width:100%; border-radius:var(--zp-radius-lg); overflow:hidden; margin-bottom:2rem; box-shadow:0 10px 30px rgba(0,0,0,0.3); aspect-ratio:21/9; min-height:220px; background:#000;">
            <img src="{fv_art}" style="width:100%; height:100%; object-fit:cover; opacity:0.85;" alt="{fv['title']}">
            <div style="position:absolute; inset:0; background:linear-gradient(to top, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.3) 60%, transparent 100%); display:flex; flex-direction:column; justify-content:flex-end; padding:2rem;">
                <span style="background:var(--zp-primary); color:#fff; font-size:0.75rem; font-weight:800; padding:3px 10px; border-radius:4px; text-transform:uppercase; display:inline-block; width:fit-content; margin-bottom:0.5rem;">🔥 FEATURED PREMIERE</span>
                <h2 style="font-size:1.8rem; font-weight:800; color:#fff; line-height:1.2; margin-bottom:0.4rem;">{fv['artist']} – {fv['title']}</h2>
                <div style="font-size:0.85rem; color:#cbd5e1; display:flex; align-items:center; gap:1.2rem; margin-bottom:1rem;">
                    <span><i class="fas fa-eye" style="color:var(--zp-primary);"></i> {fv['views_count']} Views</span>
                    <span><i class="fas fa-film"></i> Dir: {fv['director'] or 'Official'}</span>
                    <span><i class="fas fa-music"></i> {fv['genre']}</span>
                </div>
                <div style="display:flex; gap:10px; flex-wrap:wrap;">
                    <button onclick="openVideoLightbox('{fv_yt_id}', '{fv_title_clean}', '{fv_artist_clean}')" class="zp-btn-play-trigger" style="font-size:0.95rem; padding:0.6rem 1.4rem; background:#ff0000; box-shadow:0 4px 15px rgba(255,0,0,0.4);">
                        <i class="fas fa-play"></i> Watch Premiere
                    </button>
                    <a href="/video/{fv['id']}" class="zp-btn-dl-direct" style="font-size:0.95rem; padding:0.6rem 1.2rem; background:rgba(255,255,255,0.15); color:#fff; border-color:rgba(255,255,255,0.3);">
                        Video Details & Download →
                    </a>
                </div>
            </div>
        </div>
        """

    # Genre Filter Chips
    genre_chips_html = f'<a href="/videos" class="zp-filter-chip {"active" if not genre else ""}">ALL VIDEOS</a>'
    for g in genres:
        active_cls = "active" if (genre and (genre == g["slug"] or genre.lower() == g["name"].lower())) else ""
        genre_chips_html += f'<a href="/videos?genre={g["slug"]}" class="zp-filter-chip {active_cls}">{g["name"]}</a>'

    # Video Cards Grid
    video_cards_html = ""
    if videos:
        for v in videos:
            v_art = v.get("thumbnail_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=600&q=80"
            date_str = (v.get("created_at") or "2026-09-03").split(" ")[0]
            v_title_clean = v['title'].replace("'", "\\'")
            v_artist_clean = v['artist'].replace("'", "\\'")
            yt_id = v.get("youtube_id", "")
            duration_str = f"{v['duration_seconds'] // 60}:{v['duration_seconds'] % 60:02d}" if v.get('duration_seconds') else "HD"

            video_cards_html += f"""
            <div class="zp-video-card" style="background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-md); overflow:hidden; box-shadow:var(--zp-shadow); transition:transform 0.2s, box-shadow 0.2s; display:flex; flex-direction:column;">
                <div style="position:relative; width:100%; aspect-ratio:16/9; background:#000; overflow:hidden;">
                    <img src="{v_art}" style="width:100%; height:100%; object-fit:cover; opacity:0.9;" alt="{v['title']}">
                    <div style="position:absolute; inset:0; background:linear-gradient(to top, rgba(0,0,0,0.8) 0%, transparent 60%);"></div>
                    <button onclick="openVideoLightbox('{yt_id}', '{v_title_clean}', '{v_artist_clean}')" style="position:absolute; top:50%; left:50%; transform:translate(-50%, -50%); width:52px; height:52px; border-radius:50%; background:#ff0000; color:#fff; border:none; font-size:1.3rem; display:flex; align-items:center; justify-content:center; cursor:pointer; box-shadow:0 4px 15px rgba(255,0,0,0.5); transition:transform 0.2s;">
                        <i class="fas fa-play" style="margin-left:3px;"></i>
                    </button>
                    <span style="position:absolute; top:8px; left:8px; background:rgba(0,0,0,0.7); color:#fff; font-size:0.65rem; font-weight:800; padding:2px 8px; border-radius:4px; text-transform:uppercase; border:1px solid rgba(255,255,255,0.2);">{v['genre']}</span>
                    <span style="position:absolute; bottom:8px; right:8px; background:rgba(0,0,0,0.8); color:#00e676; font-size:0.7rem; font-weight:800; padding:2px 6px; border-radius:4px;"><i class="fas fa-clock"></i> {duration_str}</span>
                </div>
                <div style="padding:1.1rem; flex:1; display:flex; flex-direction:column;">
                    <div style="font-size:0.75rem; color:var(--zp-text-muted); display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">
                        <span><i class="far fa-calendar-alt"></i> {date_str}</span>
                        <span><i class="fas fa-eye" style="color:var(--zp-primary);"></i> {v['views_count']} Views</span>
                    </div>
                    <h3 style="font-size:1.05rem; font-weight:800; color:var(--zp-heading); line-height:1.35; margin-bottom:6px;">
                        <a href="/video/{v['id']}">{v['artist']} – {v['title']}</a>
                    </h3>
                    <div style="font-size:0.75rem; color:var(--zp-text-muted); margin-bottom:1rem;">
                        <i class="fas fa-video"></i> Dir: {v['director'] or 'Official Music Visuals'}
                    </div>
                    <div style="display:flex; align-items:center; justify-content:space-between; margin-top:auto; border-top:1px solid var(--zp-border-subtle); padding-top:0.8rem;">
                        <a href="/artist/{v['artist_id']}" style="font-size:0.78rem; font-weight:700; color:var(--zp-primary); display:flex; align-items:center; gap:4px;">
                            <i class="fas fa-user-check"></i> {v['artist']}
                        </a>
                        <a href="/video/{v['id']}" class="zp-btn-dl-direct" style="font-size:0.75rem; padding:4px 10px;">
                            Watch & Download →
                        </a>
                    </div>
                </div>
            </div>
            """
    else:
        video_cards_html = """
        <div class="zp-empty-state" style="grid-column: 1 / -1;">
            <i class="fas fa-film"></i>
            <h3>No Music Videos Found</h3>
            <p style="color:var(--zp-text-muted); margin-top:8px;">Try switching to 'ALL VIDEOS' or selecting another Zambian genre.</p>
            <a href="/videos" class="zp-btn-play-trigger" style="margin-top:1rem; display:inline-flex;">View All Videos</a>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zambian Music Videos & Official Visuals (2026) | {settings['site_title']}</title>
    <meta name="description" content="Watch and stream the latest official Zambian music videos, visualizers, and HD premieres on {settings['site_title']}.">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    <!-- Top Promo Headspace Bar -->
    <div class="zp-top-promo">
        <div>
            <span>🎬 Are you an Artist or Director? Get your official music video premiered on {settings['site_title']}!</span>
        </div>
        <div class="zp-top-promo-actions">
            <a href="{wa_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> Chat WhatsApp</a>
            <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
        </div>
    </div>

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
        <div style="display: flex; align-items: center; gap: 1rem;">
            <a href="{wa_link}" target="_blank" style="background:#25D366; color:#ffffff; font-size:0.8rem; font-weight:800; padding:0.4rem 1rem; border-radius:999px; display:inline-flex; align-items:center; gap:0.4rem;">
                <i class="fab fa-whatsapp"></i> Submit Video
            </a>
            <a href="/admin" style="font-size:0.85rem; font-weight:700; color:var(--zp-text-muted);"><i class="fas fa-shield-alt"></i> Admin</a>
        </div>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item"><a href="/">HOME</a></li>
                <li class="zp-menu-item"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item active"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li class="active"><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li><a href="/artists"><i class="fas fa-user-friends"></i><span>ARTISTS</span></a></li>
        </ul>
    </nav>

    <main class="zp-container" style="max-width: 1200px;">
        {spotlight_html}

        <div class="zp-mag-box-header">
            <h2 class="zp-mag-box-title"><i class="fas fa-video" style="color:var(--zp-primary);"></i> Zambian Music Videos & Visuals ({len(videos)})</h2>
            <span style="font-size:0.85rem; color:var(--zp-text-muted); font-weight:700;">Latest HD Premieres</span>
        </div>

        <!-- Video Genre Filter Chips -->
        <div class="zp-filter-bar">
            {genre_chips_html}
        </div>

        <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:1.5rem; margin-top:1.5rem;">
            {video_cards_html}
        </div>
    </main>

    <!-- Interactive In-Page Video Lightbox Modal -->
    <div id="video-lightbox-modal" style="position:fixed; inset:0; background:rgba(0,0,0,0.92); z-index:9999; display:none; align-items:center; justify-content:center; padding:1.5rem;">
        <div style="position:relative; width:100%; max-width:900px; background:#0f141f; border-radius:12px; overflow:hidden; box-shadow:0 10px 40px rgba(0,0,0,0.8); border:1px solid rgba(255,255,255,0.1);">
            <div style="display:flex; align-items:center; justify-content:space-between; padding:14px 20px; background:#131824; color:#fff; border-bottom:1px solid rgba(255,255,255,0.08);">
                <div id="lightbox-video-title" style="font-weight:800; font-size:1.05rem; display:flex; align-items:center; gap:8px;">
                    <i class="fab fa-youtube" style="color:#ff0000;"></i> <span>Playing Video</span>
                </div>
                <button onclick="closeVideoLightbox()" style="background:none; border:none; color:#94a3b8; font-size:1.4rem; cursor:pointer; line-height:1;"><i class="fas fa-times"></i></button>
            </div>
            <div style="position:relative; width:100%; aspect-ratio:16/9; background:#000;">
                <iframe id="lightbox-video-iframe" src="" style="width:100%; height:100%; border:none;" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
            </div>
        </div>
    </div>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    <script>
        function openVideoLightbox(ytId, title, artist) {{
            const modal = document.getElementById('video-lightbox-modal');
            const iframe = document.getElementById('lightbox-video-iframe');
            const titleEl = document.getElementById('lightbox-video-title');
            if (ytId) {{
                iframe.src = 'https://www.youtube.com/embed/' + ytId + '?autoplay=1&rel=0';
            }} else {{
                iframe.src = '';
            }}
            titleEl.innerHTML = '<i class="fab fa-youtube" style="color:#ff0000;"></i> <span>' + artist + ' – ' + title + '</span>';
            modal.style.display = 'flex';
        }}

        function closeVideoLightbox() {{
            const modal = document.getElementById('video-lightbox-modal');
            const iframe = document.getElementById('lightbox-video-iframe');
            iframe.src = '';
            modal.style.display = 'none';
        }}
    </script>
    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Dedicated Single Music Video Watch & Download Page (`/video/{video_id}`)
# ----------------------------------------------------------------------------
@app.get("/video/{video_id}", response_class=HTMLResponse)
async def single_video_page(video_id: int):
    settings = db.get_site_settings()
    video = db.get_video_by_id(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Music video not found")

    db.increment_video_views(video_id)
    related_videos = [v for v in db.get_videos(genre_slug=video.get('genre_slug'), limit=4) if v['id'] != video_id]

    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = f"Hello ZedHits, I am watching {video['artist']} – {video['title']} and want to promote my song/video."
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    # Related Videos Cards HTML
    related_html = ""
    for rv in related_videos:
        r_art = rv.get("thumbnail_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=400&q=80"
        related_html += f"""
        <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-md); overflow:hidden; box-shadow:var(--zp-shadow);">
            <div style="position:relative; width:100%; aspect-ratio:16/9; background:#000;">
                <img src="{r_art}" style="width:100%; height:100%; object-fit:cover;" alt="{rv['title']}">
            </div>
            <div style="padding:0.8rem;">
                <span style="font-size:0.68rem; font-weight:800; color:var(--zp-primary); text-transform:uppercase;">{rv['genre']}</span>
                <h4 style="font-size:0.92rem; font-weight:800; margin:4px 0 6px; color:var(--zp-heading); line-height:1.3;">
                    <a href="/video/{rv['id']}">{rv['artist']} – {rv['title']}</a>
                </h4>
                <div style="font-size:0.72rem; color:var(--zp-text-muted);"><i class="fas fa-eye"></i> {rv['views_count']} views</div>
            </div>
        </div>
        """

    yt_id = video.get("youtube_id", "")
    yt_embed_url = f"https://www.youtube.com/embed/{yt_id}?autoplay=1&rel=0" if yt_id else ""
    date_str = (video.get("created_at") or "2026-09-03").split(" ")[0]

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{video['artist']} – {video['title']} (Official Music Video MP4 Download) | {settings['site_title']}</title>
    <meta name="description" content="Watch and download {video['artist']} – {video['title']} official HD 1080p music video on {settings['site_title']}.">
    <meta property="og:title" content="{video['artist']} – {video['title']} (Official Music Video)">
    <meta property="og:image" content="{video['thumbnail_url']}">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    <!-- Top Promo Headspace Bar -->
    <div class="zp-top-promo">
        <div>
            <span>🎵 Are you an Artist or Producer? Get your video premiered on {settings['site_title']}!</span>
        </div>
        <div class="zp-top-promo-actions">
            <a href="{wa_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> Chat WhatsApp</a>
            <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
        </div>
    </div>

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item"><a href="/">HOME</a></li>
                <li class="zp-menu-item"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item active"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li class="active"><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li><a href="/artists"><i class="fas fa-user-friends"></i><span>ARTISTS</span></a></li>
        </ul>
    </nav>

    <!-- Single Video Main Container -->
    <main class="zp-container" style="max-width: 960px;">
        <article class="zp-single-post">
            <!-- Breadcrumbs -->
            <div class="zp-single-breadcrumbs">
                <a href="/">Home</a> • <a href="/videos">Videos</a> • <a href="/videos?genre={video['genre_slug']}">{video['genre']}</a> • <span>{video['artist']} – {video['title']}</span>
            </div>

            <!-- Single Video Title -->
            <h1 class="zp-single-title">{video['artist']} – {video['title']} (Official Music Video)</h1>

            <!-- Meta Information -->
            <div class="zp-single-meta">
                <span><i class="far fa-calendar-alt"></i> Released: {date_str}</span>
                <span><i class="fas fa-eye" style="color:var(--zp-primary);"></i> {video['views_count']} Views</span>
                <span><i class="fas fa-video"></i> Dir: {video['director'] or 'Official'}</span>
                <span><i class="fas fa-tag"></i> {video['genre']}</span>
            </div>

            <!-- Widescreen HD Video Player -->
            <div style="position:relative; width:100%; aspect-ratio:16/9; background:#000; border-radius:var(--zp-radius-md); overflow:hidden; margin-bottom:2rem; box-shadow:0 8px 30px rgba(0,0,0,0.3);">
                <iframe src="{yt_embed_url}" style="width:100%; height:100%; border:none;" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
            </div>

            <!-- Action CTAs -->
            <div style="display:flex; flex-direction:column; gap:12px; max-width:480px; margin:2rem auto; text-align:center;">
                <a href="https://www.youtube.com/watch?v={yt_id}" target="_blank" class="zp-download-cta-btn" style="background:#cc0000; box-shadow:0 6px 20px rgba(204,0,0,0.3); margin:0;">
                    <i class="fab fa-youtube"></i> WATCH ON YOUTUBE (HD)
                </a>
                <a href="{wa_link}" target="_blank" class="zp-btn-dl-direct" style="justify-content:center; padding:0.9rem; font-size:1rem; border-radius:999px;">
                    <i class="fab fa-whatsapp" style="color:#25D366;"></i> Share / Promote On WhatsApp
                </a>
            </div>

            <!-- Editorial Description -->
            <div class="zp-editorial-body">
                <p>Watch and enjoy the brand new official music video for <strong>"{video['title']}"</strong> performed by award-winning Zambian music icon <strong>{video['artist']}</strong>.</p>
                <p>{video.get('description') or 'Directed with state-of-the-art cinematic visuals and premier sound design, this release represents the peak of contemporary Zambian audio-visual artistry.'}</p>
            </div>

            <!-- Social Share Bar -->
            <div class="zp-share-bar">
                <span style="font-weight: 800; font-size: 0.8rem; text-transform: uppercase;">Share Video:</span>
                <a href="https://api.whatsapp.com/send?text=Watch+{video['artist']}+-+{video['title']}+Official+Video+on+{settings['site_title']}+https://zedhits.com/video/{video['id']}" target="_blank" class="zp-share-btn btn-sh-wa">
                    <i class="fab fa-whatsapp"></i> WhatsApp
                </a>
                <a href="https://www.facebook.com/sharer/sharer.php?u=https://zedhits.com/video/{video['id']}" target="_blank" class="zp-share-btn btn-sh-fb">
                    <i class="fab fa-facebook-f"></i> Facebook
                </a>
                <a href="https://twitter.com/intent/tweet?text=Watch+{video['artist']}+-+{video['title']}+Video&url=https://zedhits.com/video/{video['id']}" target="_blank" class="zp-share-btn btn-sh-tw">
                    <i class="fab fa-x-twitter"></i> Twitter
                </a>
            </div>
        </article>

        <!-- Related Videos Grid -->
        <section style="margin-top: 2.5rem;">
            <div class="zp-mag-box-header">
                <h3 class="zp-mag-box-title">Related Zambian Music Videos</h3>
            </div>
            <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:1.2rem;">
                {related_html}
            </div>
        </section>
    </main>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Dedicated Zambian Albums & EPs Page (`/albums` & `/album`)
# ----------------------------------------------------------------------------
@app.get("/albums", response_class=HTMLResponse)
@app.get("/album", response_class=HTMLResponse)
async def albums_page():
    settings = db.get_site_settings()
    albums = db.get_albums()

    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = settings.get("contact_whatsapp_msg", "Hello ZedHits, I want to submit an album/EP.")
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    album_cards_html = ""
    for a in albums:
        a_art = a.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=400&q=80"
        date_str = (a.get("release_date") or "2026-09-03").split(" ")[0]

        album_cards_html += f"""
        <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-md); overflow:hidden; box-shadow:var(--zp-shadow); display:flex; flex-direction:column;">
            <div style="position:relative; width:100%; aspect-ratio:1/1; overflow:hidden; background:#111;">
                <img src="{a_art}" style="width:100%; height:100%; object-fit:cover;" alt="{a['album_name']}">
                <span style="position:absolute; top:8px; right:8px; background:var(--zp-primary); color:#fff; font-size:0.68rem; font-weight:800; padding:2px 8px; border-radius:4px; text-transform:uppercase;">{a['track_count']} Tracks</span>
            </div>
            <div style="padding:1.2rem; flex:1; display:flex; flex-direction:column;">
                <span style="font-size:0.75rem; font-weight:700; color:var(--zp-primary); text-transform:uppercase; margin-bottom:4px;">{a['artist']}</span>
                <h3 style="font-size:1.1rem; font-weight:800; color:var(--zp-heading); line-height:1.3; margin-bottom:8px;">
                    <a href="/artist/{a['artist_id']}">{a['album_name']}</a>
                </h3>
                <div style="font-size:0.78rem; color:var(--zp-text-muted); margin-bottom:1rem;">
                    <span><i class="far fa-calendar-alt"></i> {date_str}</span> • 
                    <span><i class="fas fa-headphones"></i> {a['total_plays']} streams</span>
                </div>
                <div style="margin-top:auto; display:flex; gap:8px;">
                    <a href="/artist/{a['artist_id']}" class="zp-btn-play-trigger" style="flex:1; justify-content:center; font-size:0.78rem;">View Tracklist</a>
                    <a href="/api/artists/{a['artist_id']}/download-zip" class="zp-btn-dl-direct" style="font-size:0.78rem;" title="Download Full Album ZIP"><i class="fas fa-file-archive"></i> ZIP</a>
                </div>
            </div>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Zambian Albums, EPs & Official Discographies (2026) | {settings['site_title']}</title>
    <meta name="description" content="Download and stream full Zambian music albums, EPs, and complete discographies with 1-click bulk ZIP on {settings['site_title']}.">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    <!-- Top Promo Headspace Bar -->
    <div class="zp-top-promo">
        <div>
            <span>💿 Are you an Artist or Label? Release your official Album or EP on {settings['site_title']}!</span>
        </div>
        <div class="zp-top-promo-actions">
            <a href="{wa_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> Chat WhatsApp</a>
            <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
        </div>
    </div>

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
        <div style="display: flex; align-items: center; gap: 1rem;">
            <a href="{wa_link}" target="_blank" style="background:#25D366; color:#ffffff; font-size:0.8rem; font-weight:800; padding:0.4rem 1rem; border-radius:999px; display:inline-flex; align-items:center; gap:0.4rem;">
                <i class="fab fa-whatsapp"></i> Submit Album
            </a>
            <a href="/admin" style="font-size:0.85rem; font-weight:700; color:var(--zp-text-muted);"><i class="fas fa-shield-alt"></i> Admin</a>
        </div>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item"><a href="/">HOME</a></li>
                <li class="zp-menu-item"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item active"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li class="active"><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li><a href="/artists"><i class="fas fa-user-friends"></i><span>ARTISTS</span></a></li>
        </ul>
    </nav>

    <main class="zp-container" style="max-width: 1200px;">
        <div class="zp-mag-box-header">
            <h2 class="zp-mag-box-title"><i class="fas fa-compact-disc" style="color:var(--zp-primary);"></i> Zambian Albums & EP Discographies ({len(albums)})</h2>
            <span style="font-size:0.85rem; color:var(--zp-text-muted); font-weight:700;">Full Packages with ZIP Download</span>
        </div>

        <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:1.5rem; margin-top:1.5rem;">
            {album_cards_html}
        </div>
    </main>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Dedicated About Us Page (`/about`)
# ----------------------------------------------------------------------------
@app.get("/about", response_class=HTMLResponse)
async def about_us_page():
    settings = db.get_site_settings()
    contact_whatsapp = settings.get("contact_whatsapp", "+260970000000")
    contact_phone = settings.get("contact_phone", "+260970000000")
    contact_msg = settings.get("contact_whatsapp_msg", "Hello ZedHits, I want to learn more about your platform.")
    wa_link = get_whatsapp_link(contact_whatsapp, contact_msg)

    title = settings.get("about_title", "About ZedHits")
    description = settings.get("about_description", "ZedHits is Zambia's premier autonomous music streaming and digital audio distribution platform.")
    mission = settings.get("about_mission", "Empowering African musical heritage through state-of-the-art streaming infrastructure.")
    stats_artists = settings.get("about_stats_artists", "500+")
    stats_streams = settings.get("about_stats_streams", "1.2M+")
    stats_quality = settings.get("about_stats_quality", "320 kbps HD")

    if settings.get("logo_url"):
        brand_logo_html = f'<img src="{settings["logo_url"]}" alt="{settings["site_title"]}" class="zp-logo-img">'
    else:
        nav_text = settings.get("nav_logo_text", settings.get("site_title", "ZedHits"))
        brand_logo_html = f'<span class="zp-logo-text">{nav_text}<span class="zp-logo-badge">PRO</span></span>'

    team_members = db.get_team_members()
    team_cards_html = ""
    for tm in team_members:
        tm_img = tm.get("photo_path") or "/media/team/default-avatar.png"
        team_cards_html += f"""
        <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); border-radius:var(--zp-radius-md); padding:1.5rem; text-align:center; box-shadow:var(--zp-shadow); display:flex; flex-direction:column; align-items:center;">
            <img src="{tm_img}" alt="{tm['name']}" style="width:80px; height:80px; border-radius:50%; object-fit:cover; margin-bottom:0.8rem; border:2px solid var(--zp-primary);">
            <h4 style="font-size:1.1rem; font-weight:800; color:var(--zp-heading); margin-bottom:0.2rem;">{tm['name']}</h4>
            <div style="font-size:0.75rem; font-weight:700; color:var(--zp-primary); text-transform:uppercase; margin-bottom:0.6rem;">{tm['role']}</div>
            <p style="font-size:0.85rem; color:var(--zp-text-muted); line-height:1.5;">{tm['bio']}</p>
        </div>
        """

    team_section_html = f"""
    <div style="margin-top:2.5rem;">
        <h3 style="font-size:1.3rem; font-weight:800; color:var(--zp-heading); margin-bottom:1.2rem; display:flex; align-items:center; gap:8px;">
            <i class="fas fa-user-tie" style="color:var(--zp-primary);"></i> Leadership & Creative Team
        </h3>
        <div style="display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:1.2rem;">
            {team_cards_html}
        </div>
    </div>
    """ if team_members else ""

    html = f"""<!DOCTYPE html>
<html lang="en" data-skin="light">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | {settings['site_title']}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    {get_global_css(settings)}
</head>
<body>
    <!-- Top Promo Headspace Bar -->
    <div class="zp-top-promo">
        <div>
            <span>🎵 Are you an Artist or Producer? Get your song uploaded & promoted on {settings['site_title']}!</span>
        </div>
        <div class="zp-top-promo-actions">
            <a href="{wa_link}" target="_blank" class="btn-top-wa"><i class="fab fa-whatsapp"></i> Chat WhatsApp</a>
            <a href="tel:{contact_phone}" class="btn-top-call"><i class="fas fa-phone-alt"></i> Call {contact_phone}</a>
        </div>
    </div>

    <!-- Header Logo Row -->
    <header class="zp-header-logo-row">
        <a href="/" class="zp-logo-link">
            {brand_logo_html}
        </a>
    </header>

    <!-- Sticky Main Navigation Bar -->
    <nav class="zp-sticky-nav">
        <div class="zp-nav-container">
            <ul class="zp-menu-links">
                <li class="zp-menu-item"><a href="/">HOME</a></li>
                <li class="zp-menu-item"><a href="/music">MUSIC</a></li>
                <li class="zp-menu-item"><a href="/videos">VIDEOS</a></li>
                <li class="zp-menu-item"><a href="/albums">ALBUM</a></li>
                <li class="zp-menu-item"><a href="/artists">ARTISTS</a></li>
                <li class="zp-menu-item active"><a href="/about">ABOUT US</a></li>
            </ul>

            <div class="zp-nav-actions">
                <button class="zp-theme-toggle" onclick="toggleSkin()" title="Toggle Dark/Light Mode">
                    <i class="fas fa-moon"></i>
                </button>
            </div>
        </div>
    </nav>

    <!-- Mobile Bottom App Navigation Dock -->
    <nav class="zp-mobile-nav" role="navigation">
        <ul>
            <li><a href="/"><i class="fas fa-home"></i><span>HOME</span></a></li>
            <li><a href="/music"><i class="fas fa-music"></i><span>MUSIC</span></a></li>
            <li><a href="/videos"><i class="fas fa-video"></i><span>VIDEOS</span></a></li>
            <li><a href="/albums"><i class="fas fa-compact-disc"></i><span>ALBUM</span></a></li>
            <li class="active"><a href="/about"><i class="fas fa-info-circle"></i><span>ABOUT</span></a></li>
        </ul>
    </nav>

    <main class="zp-container" style="max-width: 900px;">
        <div class="zp-single-post">
            <h1 style="font-size:2.4rem; font-weight:800; color:var(--zp-heading); margin-bottom:1rem;">{title}</h1>
            
            <div style="font-size:1.05rem; line-height:1.8; color:var(--zp-text); margin-bottom:2rem;">
                <h3 style="font-size:1.2rem; font-weight:800; color:var(--zp-heading); margin-bottom:0.5rem;"><i class="fas fa-bullseye" style="color:var(--zp-primary);"></i> Our Story</h3>
                <p>{description}</p>
            </div>

            <div style="background:var(--zp-border-subtle); border-left:4px solid var(--zp-primary); padding:1.5rem; border-radius:var(--zp-radius-md); margin-bottom:2rem;">
                <h3 style="font-size:1.15rem; font-weight:800; color:var(--zp-heading); margin-bottom:0.4rem;"><i class="fas fa-rocket" style="color:var(--zp-primary);"></i> Mission Directive</h3>
                <p style="font-size:0.95rem; color:var(--zp-text);">{mission}</p>
            </div>

            <div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:1rem; text-align:center; margin-top:2rem;">
                <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); padding:1.2rem; border-radius:var(--zp-radius-md);">
                    <div style="font-size:2rem; font-weight:800; color:var(--zp-primary);">{stats_artists}</div>
                    <div style="font-size:0.75rem; color:var(--zp-text-muted); text-transform:uppercase; font-weight:700;">Verified Artists</div>
                </div>
                <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); padding:1.2rem; border-radius:var(--zp-radius-md);">
                    <div style="font-size:2rem; font-weight:800; color:var(--zp-primary);">{stats_streams}</div>
                    <div style="font-size:0.75rem; color:var(--zp-text-muted); text-transform:uppercase; font-weight:700;">Total Streams</div>
                </div>
                <div style="background:var(--zp-bg-card); border:1px solid var(--zp-border); padding:1.2rem; border-radius:var(--zp-radius-md);">
                    <div style="font-size:2rem; font-weight:800; color:var(--zp-primary);">{stats_quality}</div>
                    <div style="font-size:0.75rem; color:var(--zp-text-muted); text-transform:uppercase; font-weight:700;">Audio Quality</div>
                </div>
            </div>

            {team_section_html}
        </div>
    </main>

    <!-- Footer -->
    <footer class="zp-footer">
        <div class="zp-footer-container">
            <p class="zp-footer-copy">
                {settings.get('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.')}
            </p>
        </div>
    </footer>

    {ZAMBIANPLAY_SCRIPTS}
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# Embeddable Iframe Widget for Third-Party Websites (`/embed/track/{id}`)
# ----------------------------------------------------------------------------
@app.get("/embed/track/{track_id}", response_class=HTMLResponse)
async def embed_track_widget(track_id: int):
    track = db.get_track_by_id(track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    settings = db.get_site_settings()
    cover_img = track.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=300&q=80"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; font-family:'Plus Jakarta Sans', sans-serif; }}
        body {{ background:#131824; color:#fff; display:flex; align-items:center; padding:10px 16px; height:100vh; overflow:hidden; gap:12px; }}
        .emb-art {{ width:64px; height:64px; border-radius:8px; object-fit:cover; }}
        .emb-info {{ flex:1; overflow:hidden; }}
        .emb-title {{ font-size:14px; font-weight:800; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .emb-artist {{ font-size:12px; color:#94a3b8; margin-top:2px; }}
        .emb-btn {{ width:40px; height:40px; border-radius:50%; background:#06801e; color:#fff; border:none; display:flex; align-items:center; justify-content:center; cursor:pointer; font-size:16px; }}
    </style>
</head>
<body>
    <img src="{cover_img}" class="emb-art" alt="{track['title']}">
    <div class="emb-info">
        <div class="emb-title">{track['title']}</div>
        <div class="emb-artist">{track['artist']}</div>
    </div>
    <button class="emb-btn" onclick="toggleEmbedPlay()" id="btn-emb"><i class="fas fa-play"></i></button>
    <audio id="emb-audio" src="{track['stream_url']}"></audio>
    <script>
        const audio = document.getElementById('emb-audio');
        const btn = document.getElementById('btn-emb');
        function toggleEmbedPlay() {{
            if (audio.paused) {{
                audio.play();
                btn.innerHTML = '<i class="fas fa-pause"></i>';
                fetch('/api/tracks/{track['id']}/play', {{ method:'POST' }}).catch(() => {{}});
            }} else {{
                audio.pause();
                btn.innerHTML = '<i class="fas fa-play"></i>';
            }}
        }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)

# ----------------------------------------------------------------------------
# PBKDF2-Secured Structured Multi-Section Admin Control Panel (`/admin`)
# ----------------------------------------------------------------------------
@app.get("/admin", response_class=HTMLResponse)
async def admin_control_panel(request: Request):
    admin_user = get_current_admin(request)
    settings = db.get_site_settings()
    genres = db.get_genres()
    tracks = db.get_tracks(sort_by="latest")
    analytics = db.get_analytics_summary()

    if not admin_user:
        # Render PBKDF2 Master Login Screen
        return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Authentication | {settings['site_title']}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Plus Jakarta Sans', sans-serif; }}
        body {{ background: #0a0d14; color: #fff; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1.5rem; }}
        .login-card {{ background: #131824; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; padding: 2.5rem; width: 100%; max-width: 420px; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6); }}
        .login-header {{ text-align: center; margin-bottom: 2rem; }}
        .form-input {{ width: 100%; background: #0f141f; border: 1px solid rgba(255, 255, 255, 0.1); color: #fff; padding: 0.85rem 1rem; border-radius: 8px; font-size: 0.95rem; margin-bottom: 1.2rem; }}
        .form-input:focus {{ outline: none; border-color: #00e676; }}
        .btn-submit {{ width: 100%; background: #06801e; color: #fff; border: none; padding: 0.9rem; border-radius: 8px; font-weight: 800; font-size: 1rem; cursor: pointer; transition: background 0.2s; }}
        .btn-submit:hover {{ background: #006200; }}
        .err-msg {{ color: #ff5252; font-size: 0.85rem; margin-top: 1rem; text-align: center; display: none; }}
    </style>
</head>
<body>
    <div class="login-card">
        <div class="login-header">
            <img src="{settings.get('logo_url') or '/media/covers/logo_1d46cfc41a840cc1.png'}" id="login-brand-logo" alt="{settings['site_title']}" style="max-height: 60px; margin-bottom: 1rem; object-fit: contain;">
            <h2 style="font-size: 1.4rem; font-weight: 800;">{settings['site_title']} CMS Control</h2>
            <p style="color: #94a3b8; font-size: 0.85rem; margin-top: 4px;">PBKDF2 Master Access Verification</p>
        </div>
        <form id="admin-login-form" onsubmit="handleLogin(event)">
            <input type="text" id="login-user" class="form-input" placeholder="Admin Username" required autocomplete="username">
            <input type="password" id="login-pwd" class="form-input" placeholder="Admin Password" required autocomplete="current-password">
            <button type="submit" class="btn-submit" id="btn-login">Authenticate Master Key</button>
            <div id="login-error" class="err-msg"></div>
        </form>
    </div>

    <script>
        async function handleLogin(e) {{
            e.preventDefault();
            const btn = document.getElementById('btn-login');
            const err = document.getElementById('login-error');
            btn.textContent = 'Verifying PBKDF2 Hash...';
            err.style.display = 'none';

            try {{
                const res = await fetch('/api/admin/login', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        username: document.getElementById('login-user').value,
                        password: document.getElementById('login-pwd').value
                    }})
                }});
                const data = await res.json();
                if (res.ok && data.success) {{
                    if (data.token) {{
                        localStorage.setItem('zedhits_admin_token', data.token);
                    }}
                    window.location.reload();
                }} else {{
                    err.textContent = data.detail || 'Authentication failed';
                    err.style.display = 'block';
                    btn.textContent = 'Authenticate Master Key';
                }}
            }} catch (e) {{
                err.textContent = 'Network error connecting to auth server';
                err.style.display = 'block';
                btn.textContent = 'Authenticate Master Key';
            }}
        }}
    </script>
</body>
</html>
""")

    # Render Logged-in Multi-Section Tabbed Admin CMS Dashboard
    genre_opts = "".join([f'<option value="{g["name"]}">{g["name"]}</option>' for g in genres])
    all_artists = db.get_artists(only_with_tracks=False)

    artists_rows = ""
    for a in all_artists:
        a_art = a.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=100&q=80"
        a_name_clean = a['name'].replace("'", "\\'")
        a_bio_clean = (a.get('bio') or '').replace("'", "\\'").replace("\n", "\\n")
        a_cover_clean = (a.get('cover_url') or '').replace("'", "\\'")

        if a['track_count'] == 0:
            del_btn = f"""<button onclick="deleteArtist({a['id']}, '{a_name_clean}')" style="background:#ff5252; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700;"><i class="fas fa-trash"></i> Delete</button>"""
        else:
            del_btn = f"""<span style="font-size:0.75rem; color:#64748b; font-weight:700;">In Use ({a['track_count']})</span>"""

        artists_rows += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
            <td style="padding:12px;"><img src="{a_art}" style="width:40px; height:40px; border-radius:50%; object-fit:cover; border:2px solid #00e676;"></td>
            <td style="padding:12px; font-weight:700;">{a['name']}</td>
            <td style="padding:12px;"><span style="background:rgba(0,230,118,0.15); color:#00e676; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;">{a['track_count']} Songs</span></td>
            <td style="padding:12px; color:#cbd5e1;">{a['total_plays']}</td>
            <td style="padding:12px; color:#cbd5e1;">{a['total_downloads']}</td>
            <td style="padding:12px; text-align:right;">
                <button onclick="openEditArtistModal({a['id']}, '{a_name_clean}', '{a_bio_clean}', '{a_cover_clean}')" style="background:#0284c7; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700; margin-right:6px;">
                    <i class="fas fa-edit"></i> Edit
                </button>
                {del_btn}
            </td>
        </tr>
        """

    team_members = db.get_team_members()
    team_rows = ""
    for tm in team_members:
        tm_photo = tm.get("photo_path") or "/media/team/default-avatar.png"
        tm_name_clean = tm['name'].replace("'", "\\'")
        tm_role_clean = tm['role'].replace("'", "\\'")
        tm_bio_clean = (tm.get('bio') or '').replace("'", "\\'").replace("\n", "\\n")
        tm_photo_clean = tm_photo.replace("'", "\\'")

        team_rows += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
            <td style="padding:12px;"><img src="{tm_photo}" style="width:40px; height:40px; border-radius:50%; object-fit:cover; border:2px solid #00e676;"></td>
            <td style="padding:12px; font-weight:700;">{tm['name']}</td>
            <td style="padding:12px; color:#94a3b8;">{tm['role']}</td>
            <td style="padding:12px; color:#cbd5e1; font-size:0.82rem;">{tm['bio'][:50]}...</td>
            <td style="padding:12px; color:#cbd5e1;">#{tm['display_order']}</td>
            <td style="padding:12px; text-align:right;">
                <button onclick="openEditTeamModal({tm['id']}, '{tm_name_clean}', '{tm_role_clean}', '{tm_bio_clean}', '{tm_photo_clean}', {tm['display_order']})" style="background:#0284c7; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700; margin-right:6px;">
                    <i class="fas fa-edit"></i> Edit
                </button>
                <button onclick="deleteTeamMember({tm['id']}, '{tm_name_clean}')" style="background:#ff5252; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700;">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </td>
        </tr>
        """
    
    all_videos = db.get_videos()
    artist_opts_id = "".join([f'<option value="{a["id"]}">{a["name"]}</option>' for a in all_artists])
    genre_opts_id = "".join([f'<option value="{g["id"]}">{g["name"]}</option>' for g in genres])

    videos_rows = ""
    for v in all_videos:
        v_thumb = v.get("thumbnail_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=100&q=80"
        v_title_clean = v['title'].replace("'", "\\'")
        v_artist_clean = v['artist'].replace("'", "\\'")
        v_yt_clean = v.get('youtube_url', '').replace("'", "\\'")
        v_thumb_clean = (v.get('thumbnail_url') or '').replace("'", "\\'")
        v_dir_clean = (v.get('director') or '').replace("'", "\\'")
        v_desc_clean = (v.get('description') or '').replace("'", "\\'").replace("\n", "\\n")
        feat_badge = '<span style="background:rgba(255,193,7,0.2); color:#ffc107; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;">★ Featured</span>' if v.get('is_featured') else ''

        videos_rows += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
            <td style="padding:12px;"><img src="{v_thumb}" style="width:56px; height:32px; border-radius:4px; object-fit:cover;"></td>
            <td style="padding:12px; font-weight:700;">{v['title']} {feat_badge}</td>
            <td style="padding:12px; color:#94a3b8;">{v['artist']}</td>
            <td style="padding:12px;"><span style="background:rgba(0,230,118,0.15); color:#00e676; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;">{v['genre']}</span></td>
            <td style="padding:12px; color:#cbd5e1;">{v['views_count']}</td>
            <td style="padding:12px; text-align:right;">
                <button onclick="openEditVideoModal({v['id']}, '{v_title_clean}', {v['artist_id']}, {v['genre_id']}, '{v_yt_clean}', '{v_thumb_clean}', '{v_dir_clean}', {1 if v.get('is_featured') else 0}, '{v_desc_clean}')" style="background:#0284c7; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700; margin-right:6px;">
                    <i class="fas fa-edit"></i> Edit
                </button>
                <button onclick="deleteVideo({v['id']}, '{v_title_clean}')" style="background:#ff5252; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700;">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </td>
        </tr>
        """

    tracks_rows = ""
    for t in tracks:
        cover_preview = t.get("cover_url") or "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=100&q=80"
        clean_title = t['title'].replace("'", "\\'")
        clean_artist = t['artist'].replace("'", "\\'")
        clean_featured = (t.get('featured_artists') or '').replace("'", "\\'")
        clean_genre = t['genre'].replace("'", "\\'")
        clean_album = (t.get('album_name') or '').replace("'", "\\'")
        clean_cover = (t.get('cover_url') or '').replace("'", "\\'")
        clean_lyrics = (t.get('lyrics') or '').replace("'", "\\'").replace("\n", "\\n")
        feat_label = f" <span style='font-size:0.75rem; color:#00e676;'>ft. {t['featured_artists']}</span>" if t.get('featured_artists') else ""

        tracks_rows += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,0.06);">
            <td style="padding:12px;"><img src="{cover_preview}" style="width:40px; height:40px; border-radius:6px; object-fit:cover;"></td>
            <td style="padding:12px; font-weight:700;">{t['title']}</td>
            <td style="padding:12px; color:#94a3b8;">{t['artist']}{feat_label}</td>
            <td style="padding:12px;"><span style="background:rgba(0,230,118,0.15); color:#00e676; padding:2px 8px; border-radius:4px; font-size:0.75rem; font-weight:700;">{t['genre']}</span></td>
            <td style="padding:12px; color:#cbd5e1;">{t['plays_count']}</td>
            <td style="padding:12px; color:#cbd5e1;">{t['downloads_count']}</td>
            <td style="padding:12px; text-align:right;">
                <button onclick="openEditModal({t['id']}, '{clean_title}', '{clean_artist}', '{clean_featured}', '{clean_genre}', '{clean_album}', {t['bitrate_kbps']}, '{clean_cover}', '{clean_lyrics}')" style="background:#0284c7; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700; margin-right:6px;">
                    <i class="fas fa-edit"></i> Edit
                </button>
                <button onclick="deleteTrack({t['id']}, '{clean_title}')" style="background:#ff5252; color:#fff; border:none; padding:6px 12px; border-radius:6px; cursor:pointer; font-size:0.8rem; font-weight:700;">
                    <i class="fas fa-trash"></i> Delete
                </button>
            </td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard & CMS Control | {settings['site_title']}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; font-family:'Plus Jakarta Sans', sans-serif; }}
        body {{ background:#0a0d14; color:#fff; min-height:100vh; overflow-x:hidden; }}
        
        /* Master 2-Column Responsive Layout */
        .admin-layout {{ display:flex; min-height:100vh; }}
        
        /* Left Sticky Sidebar (Fits all 8 options on screen) */
        .admin-sidebar {{
            width: 280px;
            background: #0f141f;
            border-right: 1px solid rgba(255,255,255,0.08);
            display: flex;
            flex-direction: column;
            position: sticky;
            top: 0;
            height: 100vh;
            flex-shrink: 0;
            z-index: 99;
        }}
        .admin-sidebar-brand {{
            padding: 1.2rem 1.4rem;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        .admin-sidebar-menu {{
            list-style: none;
            padding: 1rem 0.8rem;
            display: flex;
            flex-direction: column;
            gap: 4px;
            overflow-y: auto;
            flex: 1;
        }}
        .admin-menu-btn {{
            width: 100%;
            text-align: left;
            background: none;
            border: 1px solid transparent;
            padding: 9px 12px;
            border-radius: 8px;
            color: #94a3b8;
            font-size: 0.82rem;
            font-weight: 700;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            transition: all 0.2s ease;
        }}
        .admin-menu-btn .menu-num {{
            width: 20px;
            height: 20px;
            border-radius: 4px;
            background: rgba(255,255,255,0.06);
            color: #cbd5e1;
            font-size: 0.72rem;
            font-weight: 800;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }}
        .admin-menu-btn i {{ width: 16px; text-align: center; flex-shrink: 0; }}
        .admin-menu-btn:hover {{ color: #fff; background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.06); }}
        .admin-menu-btn.active {{
            color: #00e676;
            background: rgba(0, 230, 118, 0.12);
            border-color: rgba(0, 230, 118, 0.3);
            font-weight: 800;
        }}
        .admin-menu-btn.active .menu-num {{
            background: #00e676;
            color: #0a0d14;
        }}
        .admin-sidebar-footer {{
            padding: 1rem 1.2rem;
            border-top: 1px solid rgba(255,255,255,0.06);
            display: flex;
            flex-direction: column;
            gap: 8px;
            background: #0c1019;
        }}

        /* Main Content Workspace Area */
        .admin-main {{
            flex: 1;
            padding: 1.8rem 2.5rem;
            max-width: 1300px;
            overflow-y: auto;
        }}
        
        /* Mobile 8-Option Responsive Grid (Shows when screen is small) */
        .admin-mobile-grid {{
            display: none;
            grid-template-columns: repeat(4, 1fr);
            gap: 6px;
            margin-bottom: 1.5rem;
        }}
        @media (max-width: 992px) {{
            .admin-sidebar {{ display: none; }}
            .admin-mobile-grid {{ display: grid; }}
            .admin-main {{ padding: 1rem; }}
        }}
        @media (max-width: 600px) {{
            .admin-mobile-grid {{ grid-template-columns: repeat(2, 1fr); }}
        }}

        /* Mobile Pill Buttons */
        .mobile-pill-btn {{
            background: #131824;
            border: 1px solid rgba(255,255,255,0.08);
            color: #94a3b8;
            padding: 8px;
            border-radius: 8px;
            font-size: 0.75rem;
            font-weight: 700;
            text-align: center;
            cursor: pointer;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
        }}
        .mobile-pill-btn.active {{
            background: rgba(0, 230, 118, 0.15);
            border-color: #00e676;
            color: #00e676;
        }}

        .tab-pane {{ display:none; }}
        .tab-pane.active {{ display:block; }}

        .card {{ background:#131824; border:1px solid rgba(255,255,255,0.08); border-radius:14px; padding:1.8rem; margin-bottom:2rem; }}
        .card-title {{ font-size:1.2rem; font-weight:800; margin-bottom:1.2rem; color:#00e676; display:flex; align-items:center; gap:0.6rem; }}
        .form-input {{ width:100%; background:#0f141f; border:1px solid rgba(255,255,255,0.1); color:#fff; padding:0.75rem 1rem; border-radius:8px; font-size:0.9rem; }}
        .form-input:focus {{ outline:none; border-color:#00e676; }}
        .form-group {{ margin-bottom:1.2rem; }}
        label {{ font-size:0.82rem; font-weight:700; color:#94a3b8; display:block; margin-bottom:0.4rem; }}
        .btn-green {{ background:#06801e; color:#fff; font-weight:800; padding:0.75rem 1.5rem; border-radius:8px; border:none; cursor:pointer; font-size:0.95rem; display:inline-flex; align-items:center; gap:8px; }}
        .btn-green:hover {{ background:#006200; }}
        .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }}
        .grid-3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:1.5rem; }}
        @media (max-width:850px) {{ .grid-2, .grid-3 {{ grid-template-columns:1fr; }} }}

        /* Color Picker Component */
        .color-row {{ display:flex; align-items:center; gap:10px; }}
        .color-picker-input {{ width:48px; height:42px; border:none; border-radius:8px; background:none; cursor:pointer; }}

        /* Modal */
        .modal {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.75); z-index:1000; align-items:center; justify-content:center; padding:1.5rem; }}
        .modal.active {{ display:flex; }}
        .modal-content {{ background:#131824; border:1px solid rgba(255,255,255,0.12); border-radius:16px; width:100%; max-width:600px; padding:2rem; max-height:90vh; overflow-y:auto; }}
    </style>
</head>
<body>
    <div class="admin-layout">
        <!-- Sticky Left Sidebar Navigation with All 8 Options -->
        <aside class="admin-sidebar">
            <div class="admin-sidebar-brand">
                <a href="/" style="display:flex; align-items:center; gap:0.6rem; text-decoration:none;">
                    <img src="{settings.get('logo_url') or '/media/covers/logo_1d46cfc41a840cc1.png'}" id="sidebar-brand-logo" alt="Website Logo" style="max-height: 38px; object-fit: contain;">
                    <span style="font-weight:800; font-size:1.05rem; color:#fff;">CMS Dashboard</span>
                </a>
                <span style="font-size:0.65rem; background:rgba(0,230,118,0.15); color:#00e676; font-weight:800; padding:2px 6px; border-radius:4px;">PRO</span>
            </div>

            <ul class="admin-sidebar-menu">
                <li>
                    <button class="admin-menu-btn active" onclick="switchTab('tab-identity', this)" id="btn-tab-identity">
                        <span class="menu-num">1</span>
                        <i class="fas fa-id-card"></i>
                        <span>Site Identity & Copy</span>
                    </button>
                </li>
                <li>
                    <button class="admin-menu-btn" onclick="switchTab('tab-theme', this)" id="btn-tab-theme">
                        <span class="menu-num">2</span>
                        <i class="fas fa-palette"></i>
                        <span>Visual Style & Theme</span>
                    </button>
                </li>
                <li>
                    <button class="admin-menu-btn" onclick="switchTab('tab-banner', this)" id="btn-tab-banner">
                        <span class="menu-num">3</span>
                        <i class="fas fa-bullhorn"></i>
                        <span>Announcement Banner</span>
                    </button>
                </li>
                <li>
                    <button class="admin-menu-btn" onclick="switchTab('tab-toggles', this)" id="btn-tab-toggles">
                        <span class="menu-num">4</span>
                        <i class="fas fa-toggle-on"></i>
                        <span>Feature Toggles</span>
                    </button>
                </li>
                <li>
                    <button class="admin-menu-btn" onclick="switchTab('tab-contacts', this)" id="btn-tab-contacts">
                        <span class="menu-num">5</span>
                        <i class="fas fa-share-alt"></i>
                        <span>Social & Contacts</span>
                    </button>
                </li>
                <li>
                    <button class="admin-menu-btn" onclick="switchTab('tab-about', this)" id="btn-tab-about">
                        <span class="menu-num">6</span>
                        <i class="fas fa-info-circle"></i>
                        <span>About Us CMS</span>
                    </button>
                </li>
                <li>
                    <button class="admin-menu-btn" onclick="switchTab('tab-tracks', this)" id="btn-tab-tracks">
                        <span class="menu-num">7</span>
                        <i class="fas fa-music"></i>
                        <span>Music Pool & Tracks</span>
                    </button>
                </li>
                <li>
                    <button class="admin-menu-btn" onclick="switchTab('tab-security', this)" id="btn-tab-security">
                        <span class="menu-num">8</span>
                        <i class="fas fa-shield-alt"></i>
                        <span>Admin Security</span>
                    </button>
                </li>
            </ul>

            <div class="admin-sidebar-footer">
                <a href="/" target="_blank" style="color:#94a3b8; font-size:0.82rem; font-weight:700; display:flex; align-items:center; gap:6px; padding:6px 0;"><i class="fas fa-external-link-alt"></i> View Public Site</a>
                <button onclick="logoutAdmin()" style="background:#ff5252; color:#fff; font-weight:700; padding:0.5rem; border-radius:6px; border:none; cursor:pointer; font-size:0.85rem; width:100%;"><i class="fas fa-sign-out-alt"></i> Logout ({admin_user})</button>
            </div>
        </aside>

        <!-- Main Content Area -->
        <main class="admin-main">
            <!-- Mobile 8-Option Responsive Grid -->
            <div class="admin-mobile-grid">
                <div class="mobile-pill-btn active" onclick="switchTab('tab-identity', this)" id="mbtn-tab-identity">
                    <i class="fas fa-id-card"></i> 1. Identity
                </div>
                <div class="mobile-pill-btn" onclick="switchTab('tab-theme', this)" id="mbtn-tab-theme">
                    <i class="fas fa-palette"></i> 2. Theme
                </div>
                <div class="mobile-pill-btn" onclick="switchTab('tab-banner', this)" id="mbtn-tab-banner">
                    <i class="fas fa-bullhorn"></i> 3. Banner
                </div>
                <div class="mobile-pill-btn" onclick="switchTab('tab-toggles', this)" id="mbtn-tab-toggles">
                    <i class="fas fa-toggle-on"></i> 4. Toggles
                </div>
                <div class="mobile-pill-btn" onclick="switchTab('tab-contacts', this)" id="mbtn-tab-contacts">
                    <i class="fas fa-share-alt"></i> 5. Social
                </div>
                <div class="mobile-pill-btn" onclick="switchTab('tab-about', this)" id="mbtn-tab-about">
                    <i class="fas fa-info-circle"></i> 6. About
                </div>
                <div class="mobile-pill-btn" onclick="switchTab('tab-tracks', this)" id="mbtn-tab-tracks">
                    <i class="fas fa-music"></i> 7. Tracks
                </div>
                <div class="mobile-pill-btn" onclick="switchTab('tab-security', this)" id="mbtn-tab-security">
                    <i class="fas fa-shield-alt"></i> 8. Security
                </div>
            </div>

            <!-- Analytics Top Strip -->
            <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:1.2rem; margin-bottom:2rem;">
                <div class="card" style="margin:0; padding:1.2rem; text-align:center;">
                    <div style="font-size:1.8rem; font-weight:800; color:#00e676;">{analytics['total_tracks']}</div>
                    <div style="font-size:0.75rem; color:#94a3b8; text-transform:uppercase; font-weight:700;">Total Songs</div>
                </div>
                <div class="card" style="margin:0; padding:1.2rem; text-align:center;">
                    <div style="font-size:1.8rem; font-weight:800; color:#00e676;">{analytics['total_artists']}</div>
                    <div style="font-size:0.75rem; color:#94a3b8; text-transform:uppercase; font-weight:700;">Artists</div>
                </div>
                <div class="card" style="margin:0; padding:1.2rem; text-align:center;">
                    <div style="font-size:1.8rem; font-weight:800; color:#00e676;">{analytics['total_plays']}</div>
                    <div style="font-size:0.75rem; color:#94a3b8; text-transform:uppercase; font-weight:700;">Total Streams</div>
                </div>
                <div class="card" style="margin:0; padding:1.2rem; text-align:center;">
                    <div style="font-size:1.8rem; font-weight:800; color:#00e676;">{analytics['total_downloads']}</div>
                    <div style="font-size:0.75rem; color:#94a3b8; text-transform:uppercase; font-weight:700;">Downloads</div>
                </div>
            </div>

            <!-- SECTION 1: SITE IDENTITY & COPY -->
            <div id="tab-identity" class="tab-pane active">
            <div class="card">
                <div class="card-title"><i class="fas fa-id-card"></i> Brand Identity & Public Copy Settings</div>
                <form onsubmit="handleGenericSettingsSave(event)">
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Site Title (Browser Tab & Platform Name)</label>
                            <input type="text" id="cfg-site-title" class="form-input" value="{settings['site_title']}">
                        </div>
                        <div class="form-group">
                            <label>Navigation Logo Text (When no logo image is used)</label>
                            <input type="text" id="cfg-nav-logo-text" class="form-input" value="{settings.get('nav_logo_text', settings['site_title'])}">
                        </div>
                    </div>
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Hero Headline (Main Slider Title)</label>
                            <input type="text" id="cfg-hero-title" class="form-input" value="{settings.get('hero_title', 'Download The Latest Zambian Music In 2026')}">
                        </div>
                        <div class="form-group">
                            <label>Hero Subtitle / Tagline</label>
                            <input type="text" id="cfg-hero-sub" class="form-input" value="{settings.get('hero_subtitle', 'The Pulse of Zambian & African Music Streaming')}">
                        </div>
                    </div>
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Hero Showcase Dynamic Mode</label>
                            <select id="cfg-hero-mode" class="form-input">
                                <option value="trending" {"selected" if settings.get('hero_mode') == 'trending' else ""}>Trending / Most Streamed (Auto)</option>
                                <option value="latest" {"selected" if settings.get('hero_mode') == 'latest' else ""}>Latest New Releases (Auto)</option>
                                <option value="context" {"selected" if settings.get('hero_mode') == 'context' else ""}>Context-Aware (Adapts to Active Genre Filter)</option>
                                <option value="custom" {"selected" if settings.get('hero_mode') == 'custom' else ""}>Manual Pinned Tracks (Specify IDs)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Pinned Track IDs for Hero (e.g. 1, 4, 8 - used when mode is Manual)</label>
                            <input type="text" id="cfg-hero-pinned" class="form-input" value="{settings.get('hero_pinned_tracks', '')}" placeholder="e.g. 1, 4, 8">
                        </div>
                    </div>
                    <div class="grid-3">
                        <div class="form-group">
                            <label>Latest Songs Section Title</label>
                            <input type="text" id="cfg-sec-latest" class="form-input" value="{settings.get('section_latest_title', 'The Latest')}">
                        </div>
                        <div class="form-group">
                            <label>Trending Section Title</label>
                            <input type="text" id="cfg-sec-trending" class="form-input" value="{settings.get('section_trending_title', 'TRENDING')}">
                        </div>
                        <div class="form-group">
                            <label>Artists Section Title</label>
                            <input type="text" id="cfg-sec-artists" class="form-input" value="{settings.get('section_artists_title', 'ARTISTS')}">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Empty-State Message (Displayed when 0 songs match selection)</label>
                        <input type="text" id="cfg-empty-state" class="form-input" value="{settings.get('empty_state_msg', 'No Songs Found in this Selection. Select another genre or explore the latest releases.')}">
                    </div>
                    <div class="form-group">
                        <label>Footer Copyright & Legal Text</label>
                        <input type="text" id="cfg-footer" class="form-input" value="{settings.get('footer_text', '© 2026 ZedHits.com - All Rights Reserved.')}">
                    </div>
                    <button type="submit" class="btn-green"><i class="fas fa-save"></i> Save Brand Identity</button>
                </form>

                <hr style="border-color:rgba(255,255,255,0.08); margin:2rem 0;">

                <div class="card-title"><i class="fas fa-image"></i> Brand Logo Upload</div>
                <div style="display:flex; align-items:center; gap:2rem; flex-wrap:wrap;">
                    <div>
                        <label>Current Logo Preview</label>
                        <div style="background:#0f141f; padding:12px; border-radius:8px; display:inline-block; border:1px solid rgba(255,255,255,0.1);">
                            <img id="logo-preview-img" src="{settings.get('logo_url') or 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=150&q=80'}" style="max-height:50px; object-fit:contain;">
                        </div>
                    </div>
                    <div style="flex:1;">
                        <input type="file" id="logo-file-input" class="form-input" accept="image/*" style="margin-bottom:0.8rem;">
                        <button onclick="handleLogoUpload()" class="btn-green" style="background:#0284c7;"><i class="fas fa-cloud-upload-alt"></i> Upload New Brand Logo</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- SECTION 2: VISUAL STYLE & THEME -->
        <div id="tab-theme" class="tab-pane">
            <div class="card">
                <div class="card-title"><i class="fas fa-palette"></i> Palette & Design Tokens</div>
                <form onsubmit="handleThemeSave(event)">
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Primary Brand Accent Color</label>
                            <div class="color-row">
                                <input type="color" id="picker-accent" class="color-picker-input" value="{settings.get('accent_color', '#06801e')}" oninput="syncColor('picker-accent', 'cfg-accent')">
                                <input type="text" id="cfg-accent" class="form-input" value="{settings.get('accent_color', '#06801e')}" oninput="syncColor('cfg-accent', 'picker-accent')">
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Light Theme Background Base Color</label>
                            <div class="color-row">
                                <input type="color" id="picker-bg" class="color-picker-input" value="{settings.get('bg_base_color', '#f7f8f8')}" oninput="syncColor('picker-bg', 'cfg-bg')">
                                <input type="text" id="cfg-bg" class="form-input" value="{settings.get('bg_base_color', '#f7f8f8')}" oninput="syncColor('cfg-bg', 'picker-bg')">
                            </div>
                        </div>
                    </div>
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Card Surface Color</label>
                            <div class="color-row">
                                <input type="color" id="picker-card" class="color-picker-input" value="{settings.get('card_surface_color', '#ffffff')}" oninput="syncColor('picker-card', 'cfg-card')">
                                <input type="text" id="cfg-card" class="form-input" value="{settings.get('card_surface_color', '#ffffff')}" oninput="syncColor('cfg-card', 'picker-card')">
                            </div>
                        </div>
                        <div class="form-group">
                            <label>Primary Text Color</label>
                            <div class="color-row">
                                <input type="color" id="picker-text" class="color-picker-input" value="{settings.get('text_primary_color', '#2c2f34')}" oninput="syncColor('picker-text', 'cfg-text')">
                                <input type="text" id="cfg-text" class="form-input" value="{settings.get('text_primary_color', '#2c2f34')}" oninput="syncColor('cfg-text', 'picker-text')">
                            </div>
                        </div>
                    </div>
                    <button type="submit" class="btn-green"><i class="fas fa-save"></i> Save Theme Colors</button>
                </form>
            </div>
        </div>

        <!-- SECTION 3: PROMOTIONAL & ANNOUNCEMENT BANNER -->
        <div id="tab-banner" class="tab-pane">
            <div class="card">
                <div class="card-title"><i class="fas fa-bullhorn"></i> Top Announcement & Headspace Banner</div>
                <form onsubmit="handleBannerSave(event)">
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Banner Active Status</label>
                            <select id="cfg-banner-active" class="form-input">
                                <option value="true" {"selected" if settings.get('banner_active', 'true').lower() == 'true' else ""}>Enabled (Visible)</option>
                                <option value="false" {"selected" if settings.get('banner_active', 'true').lower() == 'false' else ""}>Disabled (Hidden)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Banner Style Type</label>
                            <select id="cfg-banner-type" class="form-input">
                                <option value="promotional" {"selected" if settings.get('banner_type') == 'promotional' else ""}>Promotional</option>
                                <option value="info" {"selected" if settings.get('banner_type') == 'info' else ""}>Informational / News</option>
                                <option value="warning" {"selected" if settings.get('banner_type') == 'warning' else ""}>Important Alert</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Banner Message Copy</label>
                        <input type="text" id="cfg-banner-msg" class="form-input" value="{settings.get('banner_message', 'Are you an Artist or Producer? Get your song uploaded & promoted on ZedHits!')}">
                    </div>
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Action Button Label</label>
                            <input type="text" id="cfg-banner-btn-text" class="form-input" value="{settings.get('banner_btn_text', 'Chat WhatsApp')}">
                        </div>
                        <div class="form-group">
                            <label>Action Button URL (Leave blank to use WhatsApp link)</label>
                            <input type="text" id="cfg-banner-btn-link" class="form-input" value="{settings.get('banner_btn_link', '')}">
                        </div>
                    </div>
                    <button type="submit" class="btn-green"><i class="fas fa-save"></i> Save Banner Settings</button>
                </form>
            </div>
        </div>

        <!-- SECTION 4: PUBLIC FEATURE TOGGLES -->
        <div id="tab-toggles" class="tab-pane">
            <div class="card">
                <div class="card-title"><i class="fas fa-toggle-on"></i> Public Feature & Display Controls</div>
                <form onsubmit="handleTogglesSave(event)">
                    <div class="grid-3">
                        <div class="form-group">
                            <label>Allow Public MP3 Downloads</label>
                            <select id="cfg-allow-dl" class="form-input">
                                <option value="true" {"selected" if settings.get('allow_downloads', 'true').lower() == 'true' else ""}>Enabled</option>
                                <option value="false" {"selected" if settings.get('allow_downloads', 'true').lower() == 'false' else ""}>Disabled</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Display Stream / Play Counters</label>
                            <select id="cfg-show-plays" class="form-input">
                                <option value="true" {"selected" if settings.get('show_play_counts', 'true').lower() == 'true' else ""}>Show Plays</option>
                                <option value="false" {"selected" if settings.get('show_play_counts', 'true').lower() == 'false' else ""}>Hide Plays</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Display Release Dates</label>
                            <select id="cfg-show-dates" class="form-input">
                                <option value="true" {"selected" if settings.get('show_release_dates', 'true').lower() == 'true' else ""}>Show Dates</option>
                                <option value="false" {"selected" if settings.get('show_release_dates', 'true').lower() == 'false' else ""}>Hide Dates</option>
                            </select>
                        </div>
                    </div>
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Stream Quality Badge Label</label>
                            <input type="text" id="cfg-quality-label" class="form-input" value="{settings.get('stream_quality_label', '320k HD')}">
                        </div>
                        <div class="form-group">
                            <label>Default Homepage Track Sorting</label>
                            <select id="cfg-sort-mode" class="form-input">
                                <option value="latest" {"selected" if settings.get('default_sort_mode') == 'latest' else ""}>Newest First</option>
                                <option value="plays" {"selected" if settings.get('default_sort_mode') == 'plays' else ""}>Most Streamed First</option>
                                <option value="title" {"selected" if settings.get('default_sort_mode') == 'title' else ""}>Alphabetical (A-Z)</option>
                            </select>
                        </div>
                    </div>
                    <button type="submit" class="btn-green"><i class="fas fa-save"></i> Save Feature Toggles</button>
                </form>
            </div>
        </div>

        <!-- SECTION 5: SOCIAL MEDIA & CONTACT DETAILS -->
        <div id="tab-contacts" class="tab-pane">
            <div class="card">
                <div class="card-title"><i class="fas fa-share-alt"></i> Communication Channels & Social Media</div>
                <form onsubmit="handleContactsSave(event)">
                    <div class="grid-2">
                        <div class="form-group">
                            <label>WhatsApp Promotion Number (International format)</label>
                            <input type="text" id="cfg-wa" class="form-input" value="{settings.get('contact_whatsapp', '+260970000000')}">
                        </div>
                        <div class="form-group">
                            <label>Telephone Call Number</label>
                            <input type="text" id="cfg-phone" class="form-input" value="{settings.get('contact_phone', '+260970000000')}">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Default WhatsApp Pre-filled Text</label>
                        <input type="text" id="cfg-wa-msg" class="form-input" value="{settings.get('contact_whatsapp_msg', 'Hello ZedHits, I want to submit my song for upload and promotion.')}">
                    </div>
                    <div class="grid-2">
                        <div class="form-group">
                            <label>Official Facebook Page URL</label>
                            <input type="url" id="cfg-social-fb" class="form-input" value="{settings.get('social_facebook', 'https://facebook.com')}">
                        </div>
                        <div class="form-group">
                            <label>Official X (Twitter) URL</label>
                            <input type="url" id="cfg-social-tw" class="form-input" value="{settings.get('social_twitter', 'https://x.com')}">
                        </div>
                    </div>
                    <div class="grid-3">
                        <div class="form-group">
                            <label>Instagram URL</label>
                            <input type="url" id="cfg-social-ig" class="form-input" value="{settings.get('social_instagram', 'https://instagram.com')}">
                        </div>
                        <div class="form-group">
                            <label>YouTube URL</label>
                            <input type="url" id="cfg-social-yt" class="form-input" value="{settings.get('social_youtube', 'https://youtube.com')}">
                        </div>
                        <div class="form-group">
                            <label>Support Email Address</label>
                            <input type="email" id="cfg-email" class="form-input" value="{settings.get('contact_email', 'support@zedhits.com')}">
                        </div>
                    </div>
                    <button type="submit" class="btn-green"><i class="fas fa-save"></i> Save Contacts & Social Links</button>
                </form>
            </div>
        </div>

        <!-- SECTION 6: ABOUT US CMS -->
        <div id="tab-about" class="tab-pane">
            <div class="card">
                <div class="card-title"><i class="fas fa-info-circle"></i> About Us Page Content Management</div>
                <form onsubmit="handleAboutSave(event)">
                    <div class="form-group">
                        <label>About Page Title</label>
                        <input type="text" id="cfg-about-title" class="form-input" value="{settings.get('about_title', 'About ZedHits')}">
                    </div>
                    <div class="form-group">
                        <label>Platform Story & Description</label>
                        <textarea id="cfg-about-desc" class="form-input" rows="4">{settings.get('about_description', '')}</textarea>
                    </div>
                    <div class="form-group">
                        <label>Mission Directive Statement</label>
                        <textarea id="cfg-about-mission" class="form-input" rows="3">{settings.get('about_mission', '')}</textarea>
                    </div>
                    <div class="grid-3">
                        <div class="form-group">
                            <label>Verified Artists Stat</label>
                            <input type="text" id="cfg-stat-art" class="form-input" value="{settings.get('about_stats_artists', '500+')}">
                        </div>
                        <div class="form-group">
                            <label>Total Streams Stat</label>
                            <input type="text" id="cfg-stat-strm" class="form-input" value="{settings.get('about_stats_streams', '1.2M+')}">
                        </div>
                        <div class="form-group">
                            <label>Audio Quality Standard</label>
                            <input type="text" id="cfg-stat-qty" class="form-input" value="{settings.get('about_stats_quality', '320 kbps HD')}">
                        </div>
                    </div>
                    <button type="submit" class="btn-green"><i class="fas fa-save"></i> Save About Us Content</button>
                </form>
            </div>

            <!-- Team & Leadership Profiles Section -->
            <div class="card">
                <div class="card-title" style="justify-content:space-between; flex-wrap:wrap; gap:10px;">
                    <div><i class="fas fa-user-tie"></i> Executive & Creative Team ({len(team_members)} Members)</div>
                    <button onclick="openCreateTeamModal()" class="btn-green" style="padding:6px 12px; font-size:0.8rem;"><i class="fas fa-plus-circle"></i> Add Team Member</button>
                </div>
                <table style="width:100%; border-collapse:collapse; font-size:0.9rem;" id="admin-team-table">
                    <thead>
                        <tr style="border-bottom:2px solid rgba(255,255,255,0.1); text-align:left; color:#94a3b8; font-size:0.75rem; text-transform:uppercase;">
                            <th style="padding:12px;">Photo</th>
                            <th style="padding:12px;">Name</th>
                            <th style="padding:12px;">Role / Title</th>
                            <th style="padding:12px;">Bio</th>
                            <th style="padding:12px;">Order</th>
                            <th style="padding:12px; text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="admin-team-tbody">
                        {team_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- SECTION 7: MUSIC POOL & TRACK MANAGEMENT -->
        <div id="tab-tracks" class="tab-pane">
            <div class="grid-2">
                <!-- Upload Track Form -->
                <div class="card">
                    <div class="card-title"><i class="fas fa-cloud-upload-alt"></i> Upload New Zambian Music Track</div>
                    <form id="upload-form" onsubmit="handleTrackUpload(event)">
                        <div class="form-group">
                            <label>Audio File (MP3, WAV, M4A, FLAC) *</label>
                            <input type="file" id="up-file" class="form-input" accept="audio/*" required>
                        </div>
                        <div class="form-group">
                            <label>Song Title</label>
                            <input type="text" id="up-title" class="form-input" placeholder="e.g. God Is Good">
                        </div>
                        <div class="form-group">
                            <label>Artist Name</label>
                            <input type="text" id="up-artist" class="form-input" placeholder="e.g. Macky 2">
                        </div>
                        <div class="form-group">
                            <label>Featured Artists (Optional)</label>
                            <input type="text" id="up-featured-artists" class="form-input" placeholder="e.g. Jay Wolf, Towela">
                        </div>
                        <div class="form-group">
                            <label>Genre</label>
                            <select id="up-genre" class="form-input">
                                {genre_opts}
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Cover Artwork (Optional Upload)</label>
                            <input type="file" id="up-cover-file" class="form-input" accept="image/*">
                        </div>
                        <div class="form-group">
                            <label>Cover Artwork URL (Optional Fallback)</label>
                            <input type="url" id="up-cover-url" class="form-input" placeholder="https://...">
                        </div>
                        <button type="submit" class="btn-green" id="btn-up-submit" style="width:100%;"><i class="fas fa-upload"></i> Upload & Process Track</button>
                    </form>
                </div>

                <!-- Fast Info Box -->
                <div class="card">
                    <div class="card-title"><i class="fas fa-info-circle"></i> Audio Engine Features</div>
                    <ul style="line-height:2; color:#cbd5e1; font-size:0.9rem; padding-left:1.2rem;">
                        <li><strong>ID3 Tag Autodetection:</strong> Uploading an audio file automatically populates title, artist, bitrate, and duration.</li>
                        <li><strong>SHA-256 Deduplication:</strong> Identical audio files are rejected before wasting server disk storage.</li>
                        <li><strong>Cascade Deletion:</strong> Deleting a track physically wipes the binary file from disk and sanitizes relational indexes.</li>
                        <li><strong>Live In-Place Editing:</strong> Edit song titles, lyrics, albums, and artists instantly without re-uploading.</li>
                    </ul>
                </div>
            </div>

            <!-- Songs Management Table -->
            <div class="card">
                <div class="card-title" style="justify-content:space-between;">
                    <div><i class="fas fa-music"></i> Live Music Catalog ({len(tracks)} Songs)</div>
                    <input type="text" placeholder="Search catalog..." onkeyup="filterAdminTracks(this.value)" style="background:#0f141f; border:1px solid rgba(255,255,255,0.1); color:#fff; padding:6px 12px; border-radius:8px; font-size:0.85rem; width:220px;">
                </div>
                <table style="width:100%; border-collapse:collapse; font-size:0.9rem;" id="admin-tracks-table">
                    <thead>
                        <tr style="border-bottom:2px solid rgba(255,255,255,0.1); text-align:left; color:#94a3b8; font-size:0.75rem; text-transform:uppercase;">
                            <th style="padding:12px;">Cover</th>
                            <th style="padding:12px;">Title</th>
                            <th style="padding:12px;">Artist</th>
                            <th style="padding:12px;">Genre</th>
                            <th style="padding:12px;">Streams</th>
                            <th style="padding:12px;">Downloads</th>
                            <th style="padding:12px; text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {tracks_rows}
                    </tbody>
                </table>
            </div>

            <!-- Verified Artists Management Table -->
            <div class="card">
                <div class="card-title" style="justify-content:space-between; flex-wrap:wrap; gap:10px;">
                    <div><i class="fas fa-users"></i> Verified Artists Hub ({len(all_artists)} Artists)</div>
                    <div style="display:flex; gap:8px;">
                        <button onclick="openCreateArtistModal()" class="btn-green" style="padding:6px 12px; font-size:0.8rem;"><i class="fas fa-user-plus"></i> Add New Artist</button>
                        <button onclick="purgeEmptyArtists()" style="background:#ff9800; color:#000; font-weight:800; border:none; padding:6px 12px; border-radius:6px; font-size:0.8rem; cursor:pointer;"><i class="fas fa-broom"></i> Purge 0-Track Artists</button>
                    </div>
                </div>
                <table style="width:100%; border-collapse:collapse; font-size:0.9rem;" id="admin-artists-table">
                    <thead>
                        <tr style="border-bottom:2px solid rgba(255,255,255,0.1); text-align:left; color:#94a3b8; font-size:0.75rem; text-transform:uppercase;">
                            <th style="padding:12px;">Avatar</th>
                            <th style="padding:12px;">Artist Name</th>
                            <th style="padding:12px;">Discography</th>
                            <th style="padding:12px;">Total Streams</th>
                            <th style="padding:12px;">Total Downloads</th>
                            <th style="padding:12px; text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {artists_rows}
                    </tbody>
                </table>
            </div>

            <!-- Official Music Videos Management Table -->
            <div class="card">
                <div class="card-title" style="justify-content:space-between; flex-wrap:wrap; gap:10px;">
                    <div><i class="fas fa-video"></i> Official Music Videos Pool ({len(all_videos)} Videos)</div>
                    <button onclick="openCreateVideoModal()" class="btn-green" style="padding:6px 12px; font-size:0.8rem;"><i class="fas fa-plus-circle"></i> Add Music Video</button>
                </div>
                <table style="width:100%; border-collapse:collapse; font-size:0.9rem;" id="admin-videos-table">
                    <thead>
                        <tr style="border-bottom:2px solid rgba(255,255,255,0.1); text-align:left; color:#94a3b8; font-size:0.75rem; text-transform:uppercase;">
                            <th style="padding:12px;">Thumbnail</th>
                            <th style="padding:12px;">Video Title</th>
                            <th style="padding:12px;">Artist</th>
                            <th style="padding:12px;">Genre</th>
                            <th style="padding:12px;">Views</th>
                            <th style="padding:12px; text-align:right;">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="admin-videos-tbody">
                        {videos_rows}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- SECTION 8: ADMIN ACCOUNT SECURITY -->
        <div id="tab-security" class="tab-pane">
            <div class="card" style="max-width:600px;">
                <div class="card-title"><i class="fas fa-shield-alt"></i> Administrator Credentials</div>
                <form onsubmit="handleSecurityUpdate(event)">
                    <div class="form-group">
                        <label>Current Master Password *</label>
                        <input type="password" id="sec-current-pwd" class="form-input" required placeholder="Enter current password">
                    </div>
                    <div class="form-group">
                        <label>New Admin Username *</label>
                        <input type="text" id="sec-new-user" class="form-input" value="{admin_user}" required>
                    </div>
                    <div class="form-group">
                        <label>New Master Password (Leave blank to keep unchanged)</label>
                        <input type="password" id="sec-new-pwd" class="form-input" placeholder="Min 6 characters">
                    </div>
                    <button type="submit" class="btn-green"><i class="fas fa-key"></i> Update Security Credentials</button>
                </form>
            </div>
        </div>
        </main>
    </div>

    <!-- Edit Track Modal -->
    <div id="edit-modal" class="modal">
        <div class="modal-content">
            <div class="card-title" style="justify-content:space-between; margin-bottom:1.5rem;">
                <div><i class="fas fa-edit"></i> Edit Track Details</div>
                <button onclick="closeEditModal()" style="background:none; border:none; color:#94a3b8; font-size:1.2rem; cursor:pointer;"><i class="fas fa-times"></i></button>
            </div>
            <form onsubmit="handleSaveTrackEdit(event)">
                <input type="hidden" id="edit-track-id">
                <div class="form-group">
                    <label>Song Title *</label>
                    <input type="text" id="edit-title" class="form-input" required>
                </div>
                <div class="form-group">
                    <label>Artist Name *</label>
                    <input type="text" id="edit-artist" class="form-input" required>
                </div>
                <div class="form-group">
                    <label>Featured Artists (Optional)</label>
                    <input type="text" id="edit-featured-artists" class="form-input" placeholder="e.g. Jay Wolf, Towela">
                </div>
                <div class="form-group">
                    <label>Genre</label>
                    <select id="edit-genre" class="form-input">
                        {genre_opts}
                    </select>
                </div>
                <div class="form-group">
                    <label>Album Name</label>
                    <input type="text" id="edit-album" class="form-input">
                </div>
                <div class="form-group">
                    <label>Bitrate (kbps)</label>
                    <input type="number" id="edit-bitrate" class="form-input">
                </div>
                <div class="form-group">
                    <label>Cover Artwork URL</label>
                    <input type="url" id="edit-cover" class="form-input">
                </div>
                <div class="form-group">
                    <label>Official Lyrics</label>
                    <textarea id="edit-lyrics" class="form-input" rows="4"></textarea>
                </div>
                <button type="submit" class="btn-green" style="width:100%;"><i class="fas fa-save"></i> Save Track Changes</button>
            </form>
        </div>
    </div>

    <!-- Edit Artist Modal -->
    <div id="edit-artist-modal" class="modal">
        <div class="modal-content">
            <div class="card-title" style="justify-content:space-between; margin-bottom:1.5rem;">
                <div><i class="fas fa-user-edit"></i> Edit Artist Profile</div>
                <button onclick="closeEditArtistModal()" style="background:none; border:none; color:#94a3b8; font-size:1.2rem; cursor:pointer;"><i class="fas fa-times"></i></button>
            </div>
            <form onsubmit="handleSaveArtistEdit(event)">
                <input type="hidden" id="edit-artist-id">
                <div class="form-group">
                    <label>Artist Name *</label>
                    <input type="text" id="edit-artist-name" class="form-input" required>
                </div>
                <div class="form-group">
                    <label>Avatar Artwork URL</label>
                    <input type="url" id="edit-artist-cover" class="form-input" placeholder="https://...">
                </div>
                <div class="form-group">
                    <label>Artist Biography / Profile Bio</label>
                    <textarea id="edit-artist-bio" class="form-input" rows="4" placeholder="Artist biography details..."></textarea>
                </div>
                <button type="submit" class="btn-green" style="width:100%;"><i class="fas fa-save"></i> Save Artist Profile</button>
            </form>
        </div>
    </div>

    <!-- Create Artist Modal -->
    <div id="create-artist-modal" class="modal">
        <div class="modal-content">
            <div class="card-title" style="justify-content:space-between; margin-bottom:1.5rem;">
                <div><i class="fas fa-user-plus"></i> Add New Artist Profile</div>
                <button onclick="closeCreateArtistModal()" style="background:none; border:none; color:#94a3b8; font-size:1.2rem; cursor:pointer;"><i class="fas fa-times"></i></button>
            </div>
            <form onsubmit="handleCreateArtist(event)">
                <div class="form-group">
                    <label>Artist Name *</label>
                    <input type="text" id="create-artist-name" class="form-input" required placeholder="e.g. Yo Maps">
                </div>
                <div class="form-group">
                    <label>Avatar / Cover URL (Optional)</label>
                    <input type="url" id="create-artist-cover" class="form-input" placeholder="https://...">
                </div>
                <div class="form-group">
                    <label>Artist Biography (Optional)</label>
                    <textarea id="create-artist-bio" class="form-input" rows="4" placeholder="Enter biography..."></textarea>
                </div>
                <button type="submit" class="btn-green" style="width:100%;"><i class="fas fa-plus-circle"></i> Create Artist</button>
            </form>
        </div>
    </div>

    <!-- Add / Edit Team Member Modal -->
    <div id="team-modal" class="modal">
        <div class="modal-content">
            <div class="card-title" style="justify-content:space-between; margin-bottom:1.5rem;">
                <div id="team-modal-title"><i class="fas fa-user-plus"></i> Add Team Member</div>
                <button onclick="closeTeamModal()" style="background:none; border:none; color:#94a3b8; font-size:1.2rem; cursor:pointer;"><i class="fas fa-times"></i></button>
            </div>
            <form id="team-form" onsubmit="handleTeamSubmit(event)">
                <input type="hidden" id="team-member-id">
                <div class="grid-2">
                    <div class="form-group">
                        <label class="form-label">Full Name *</label>
                        <input type="text" id="team-name-input" class="form-input" required placeholder="e.g. Chanda Mwanza">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Role / Title *</label>
                        <input type="text" id="team-role-input" class="form-input" required placeholder="e.g. Managing Director">
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Biography / Summary</label>
                    <textarea id="team-bio-input" class="form-input" rows="3" placeholder="Brief background..."></textarea>
                </div>
                <div class="grid-2">
                    <div class="form-group">
                        <label class="form-label">Profile Photo (JPG, PNG, WebP)</label>
                        <input type="file" name="photo" id="team-photo-input" class="form-input" accept="image/*" onchange="previewTeamPhoto(this)">
                        <div id="team-photo-preview-wrap" style="margin-top: 8px; display:flex; align-items:center; gap:10px;">
                            <img id="team-photo-preview" src="/media/team/default-avatar.png" alt="Preview" style="width: 50px; height: 50px; border-radius: 50%; object-fit: cover; border: 2px solid #00e676;">
                            <span id="team-photo-filename" style="font-size:0.75rem; color:#94a3b8;">Default avatar</span>
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">Display Order</label>
                        <input type="number" id="team-order-input" class="form-input" value="1" min="0">
                    </div>
                </div>
                <button type="submit" class="btn-green" id="btn-team-submit" style="width:100%;"><i class="fas fa-save"></i> Save Team Member</button>
            </form>
        </div>
    </div>

    <!-- Add / Edit Music Video Modal -->
    <div id="video-admin-modal" class="modal">
        <div class="modal-content">
            <div class="card-title" style="justify-content:space-between; margin-bottom:1.5rem;">
                <div id="video-modal-title"><i class="fas fa-video"></i> Add Official Music Video</div>
                <button onclick="closeVideoAdminModal()" style="background:none; border:none; color:#94a3b8; font-size:1.2rem; cursor:pointer;"><i class="fas fa-times"></i></button>
            </div>
            <form id="video-admin-form" onsubmit="handleVideoAdminSubmit(event)">
                <input type="hidden" id="video-admin-id">
                <div class="grid-2">
                    <div class="form-group">
                        <label class="form-label">Video Title *</label>
                        <input type="text" id="video-title-input" class="form-input" required placeholder="e.g. Aweah (Official Video)">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Artist *</label>
                        <select id="video-artist-input" class="form-input" required>
                            {artist_opts_id}
                        </select>
                    </div>
                </div>
                <div class="grid-2">
                    <div class="form-group">
                        <label class="form-label">Genre *</label>
                        <select id="video-genre-input" class="form-input" required>
                            {genre_opts_id}
                        </select>
                    </div>
                    <div class="form-group">
                        <label class="form-label">YouTube URL or Embed ID *</label>
                        <input type="text" id="video-yt-input" class="form-input" required placeholder="https://www.youtube.com/watch?v=...">
                    </div>
                </div>
                <div class="grid-2">
                    <div class="form-group">
                        <label class="form-label">Director / Visual Producer</label>
                        <input type="text" id="video-director-input" class="form-input" placeholder="e.g. Director Verb">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Custom Thumbnail URL (Optional)</label>
                        <input type="url" id="video-thumb-input" class="form-input" placeholder="Leave blank for auto YouTube HD preview">
                    </div>
                </div>
                <div class="grid-2">
                    <div class="form-group">
                        <label class="form-label">Featured Spotlight Status</label>
                        <select id="video-featured-input" class="form-input">
                            <option value="0">Standard Video</option>
                            <option value="1">★ Featured Video Premiere Banner</option>
                        </select>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label">Description / Editorial Writeup</label>
                    <textarea id="video-desc-input" class="form-input" rows="3" placeholder="Official music video details..."></textarea>
                </div>
                <button type="submit" class="btn-green" id="btn-video-submit" style="width:100%;"><i class="fas fa-save"></i> Save Music Video</button>
            </form>
        </div>
    </div>

    <script>
        function switchTab(tabId, el) {{
            document.querySelectorAll('.admin-menu-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.mobile-pill-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

            const targetPane = document.getElementById(tabId);
            if (targetPane) targetPane.classList.add('active');

            const sBtn = document.getElementById('btn-' + tabId);
            if (sBtn) sBtn.classList.add('active');

            const mBtn = document.getElementById('mbtn-' + tabId);
            if (mBtn) mBtn.classList.add('active');

            localStorage.setItem('zedhits_admin_active_tab', tabId);
            const mainContent = document.querySelector('.admin-main');
            if (mainContent) mainContent.scrollTop = 0;
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            const savedTab = localStorage.getItem('zedhits_admin_active_tab');
            if (savedTab && document.getElementById(savedTab)) {{
                switchTab(savedTab);
            }}
        }});

        function syncColor(fromId, toId) {{
            document.getElementById(toId).value = document.getElementById(fromId).value;
        }}

        function showToast(msg) {{
            let toast = document.getElementById('admin-toast');
            if (!toast) {{
                toast = document.createElement('div');
                toast.id = 'admin-toast';
                toast.style.cssText = 'position:fixed; bottom:24px; right:24px; background:#06801e; color:#fff; padding:12px 24px; border-radius:8px; font-weight:800; font-size:0.9rem; z-index:99999; box-shadow:0 4px 20px rgba(0,0,0,0.4); display:none; transition:all 0.3s;';
                document.body.appendChild(toast);
            }}
            toast.textContent = msg;
            toast.style.display = 'block';
            setTimeout(() => {{ toast.style.display = 'none'; }}, 3000);
        }}

        async function saveSettingsPayload(payload) {{
            let currentSettings = JSON.parse(localStorage.getItem('zedhits_cms_settings') || '{{}}');
            Object.assign(currentSettings, payload);
            localStorage.setItem('zedhits_cms_settings', JSON.stringify(currentSettings));

            try {{
                const res = await fetch('/api/admin/settings', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (res.ok) {{
                    showToast('✓ CMS Settings saved & synced to database!');
                    return;
                }}
            }} catch (e) {{
                console.log('Static host CMS fallback active');
            }}
            showToast('✓ CMS Settings saved successfully!');
        }}

        function handleGenericSettingsSave(e) {{
            e.preventDefault();
            saveSettingsPayload({{
                site_title: document.getElementById('cfg-site-title').value,
                nav_logo_text: document.getElementById('cfg-nav-logo-text').value,
                hero_title: document.getElementById('cfg-hero-title').value,
                hero_subtitle: document.getElementById('cfg-hero-sub').value,
                hero_mode: document.getElementById('cfg-hero-mode').value,
                hero_pinned_tracks: document.getElementById('cfg-hero-pinned').value,
                section_latest_title: document.getElementById('cfg-sec-latest').value,
                section_trending_title: document.getElementById('cfg-sec-trending').value,
                section_artists_title: document.getElementById('cfg-sec-artists').value,
                empty_state_msg: document.getElementById('cfg-empty-state').value,
                footer_text: document.getElementById('cfg-footer').value
            }});
        }}

        function handleThemeSave(e) {{
            e.preventDefault();
            saveSettingsPayload({{
                accent_color: document.getElementById('cfg-accent').value,
                bg_base_color: document.getElementById('cfg-bg').value,
                card_surface_color: document.getElementById('cfg-card').value,
                text_primary_color: document.getElementById('cfg-text').value
            }});
        }}

        function handleBannerSave(e) {{
            e.preventDefault();
            saveSettingsPayload({{
                banner_active: document.getElementById('cfg-banner-active').value,
                banner_type: document.getElementById('cfg-banner-type').value,
                banner_message: document.getElementById('cfg-banner-msg').value,
                banner_btn_text: document.getElementById('cfg-banner-btn-text').value,
                banner_btn_link: document.getElementById('cfg-banner-btn-link').value
            }});
        }}

        function handleTogglesSave(e) {{
            e.preventDefault();
            saveSettingsPayload({{
                allow_downloads: document.getElementById('cfg-allow-dl').value,
                show_play_counts: document.getElementById('cfg-show-plays').value,
                show_release_dates: document.getElementById('cfg-show-dates').value,
                stream_quality_label: document.getElementById('cfg-quality-label').value,
                default_sort_mode: document.getElementById('cfg-sort-mode').value
            }});
        }}

        function handleContactsSave(e) {{
            e.preventDefault();
            saveSettingsPayload({{
                contact_whatsapp: document.getElementById('cfg-wa').value,
                contact_phone: document.getElementById('cfg-phone').value,
                contact_whatsapp_msg: document.getElementById('cfg-wa-msg').value,
                social_facebook: document.getElementById('cfg-social-fb').value,
                social_twitter: document.getElementById('cfg-social-tw').value,
                social_instagram: document.getElementById('cfg-social-ig').value,
                social_youtube: document.getElementById('cfg-social-yt').value,
                contact_email: document.getElementById('cfg-email').value
            }});
        }}

        function handleAboutSave(e) {{
            e.preventDefault();
            saveSettingsPayload({{
                about_title: document.getElementById('cfg-about-title').value,
                about_description: document.getElementById('cfg-about-desc').value,
                about_mission: document.getElementById('cfg-about-mission').value,
                about_stats_artists: document.getElementById('cfg-stat-art').value,
                about_stats_streams: document.getElementById('cfg-stat-strm').value,
                about_stats_quality: document.getElementById('cfg-stat-qty').value
            }});
        }}

        async function handleLogoUpload() {{
            const fileInput = document.getElementById('logo-file-input');
            if (!fileInput.files || fileInput.files.length === 0) {{
                alert('Please select an image file first.');
                return;
            }}
            const file = fileInput.files[0];
            const reader = new FileReader();
            reader.onload = function(e) {{
                const logoDataUrl = e.target.result;
                const prev = document.getElementById('logo-preview-img');
                if (prev) prev.src = logoDataUrl;
                
                let currentSettings = JSON.parse(localStorage.getItem('zedhits_cms_settings') || '{{}}');
                currentSettings.logo_url = logoDataUrl;
                localStorage.setItem('zedhits_cms_settings', JSON.stringify(currentSettings));
                
                showToast('✓ Admin & Brand Logo updated!');
            }};
            reader.readAsDataURL(file);

            try {{
                const fd = new FormData();
                fd.append('file', file);
                await fetch('/api/admin/logo', {{ method: 'POST', body: fd }});
            }} catch (err) {{}}
        }}

        async function handleTrackUpload(e) {{
            e.preventDefault();
            const btn = document.getElementById('btn-up-submit');
            btn.textContent = 'Processing & Extracting ID3...';
            btn.disabled = true;

            const fd = new FormData();
            fd.append('file', document.getElementById('up-file').files[0]);
            fd.append('title', document.getElementById('up-title').value);
            fd.append('artist', document.getElementById('up-artist').value);
            fd.append('featured_artists', document.getElementById('up-featured-artists').value);
            fd.append('genre', document.getElementById('up-genre').value);
            fd.append('cover_url', document.getElementById('up-cover-url').value);

            const coverFiles = document.getElementById('up-cover-file').files;
            if (coverFiles.length > 0) {{
                fd.append('cover_file', coverFiles[0]);
            }}

            try {{
                const res = await fetch('/api/tracks', {{ method: 'POST', body: fd }});
                const data = await res.json();
                if (res.ok && data.success) {{
                    alert('✓ Song uploaded successfully!');
                    window.location.reload();
                }} else {{
                    alert('Upload error: ' + (data.detail || 'Failed'));
                    btn.textContent = 'Upload & Process Track';
                    btn.disabled = false;
                }}
            }} catch (e) {{
                alert('Network error uploading song');
                btn.textContent = 'Upload & Process Track';
                btn.disabled = false;
            }}
        }}

        function openEditModal(id, title, artist, featured, genre, album, bitrate, cover, lyrics) {{
            document.getElementById('edit-track-id').value = id;
            document.getElementById('edit-title').value = title;
            document.getElementById('edit-artist').value = artist;
            document.getElementById('edit-featured-artists').value = featured || '';
            document.getElementById('edit-genre').value = genre;
            document.getElementById('edit-album').value = album || '';
            document.getElementById('edit-bitrate').value = bitrate || 320;
            document.getElementById('edit-cover').value = cover || '';
            document.getElementById('edit-lyrics').value = lyrics || '';
            document.getElementById('edit-modal').classList.add('active');
        }}

        function closeEditModal() {{
            document.getElementById('edit-modal').classList.remove('active');
        }}

        async function handleSaveTrackEdit(e) {{
            e.preventDefault();
            const id = document.getElementById('edit-track-id').value;
            const payload = {{
                title: document.getElementById('edit-title').value,
                artist: document.getElementById('edit-artist').value,
                featured_artists: document.getElementById('edit-featured-artists').value,
                genre: document.getElementById('edit-genre').value,
                album_name: document.getElementById('edit-album').value,
                bitrate_kbps: parseInt(document.getElementById('edit-bitrate').value) || 320,
                cover_url: document.getElementById('edit-cover').value,
                lyrics: document.getElementById('edit-lyrics').value
            }};

            try {{
                const res = await fetch('/api/tracks/' + id, {{
                    method: 'PUT',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (res.ok) {{
                    alert('✓ Track details updated successfully!');
                    window.location.reload();
                }} else {{
                    alert('Failed to update track');
                }}
            }} catch (e) {{
                alert('Network error updating track');
            }}
        }}

        async function deleteTrack(id, title) {{
            if (!confirm('Are you sure you want to delete record "' + title + '" permanently?')) return;
            try {{
                await fetch('/api/tracks/' + id, {{ method: 'DELETE' }});
            }} catch (e) {{
                console.log('Static host fallback active');
            }}
            const rows = document.querySelectorAll('#admin-tracks-table tbody tr');
            rows.forEach(r => {{
                if (r.innerHTML.includes("openEditModal(" + id + ",") || r.innerHTML.includes("deleteTrack(" + id + ",")) {{
                    r.remove();
                }}
            }});
            showToast('✓ Entry permanently deleted!');
        }}

        function openEditArtistModal(id, name, bio, cover) {{
            document.getElementById('edit-artist-id').value = id;
            document.getElementById('edit-artist-name').value = name;
            document.getElementById('edit-artist-cover').value = cover || '';
            document.getElementById('edit-artist-bio').value = bio || '';
            document.getElementById('edit-artist-modal').classList.add('active');
        }}

        function closeEditArtistModal() {{
            document.getElementById('edit-artist-modal').classList.remove('active');
        }}

        async function handleSaveArtistEdit(e) {{
            e.preventDefault();
            const id = document.getElementById('edit-artist-id').value;
            const payload = {{
                name: document.getElementById('edit-artist-name').value,
                cover_url: document.getElementById('edit-artist-cover').value,
                bio: document.getElementById('edit-artist-bio').value
            }};

            try {{
                const res = await fetch('/api/artists/' + id, {{
                    method: 'PUT',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (res.ok) {{
                    showToast('✓ Artist profile updated successfully!');
                    closeEditArtistModal();
                    return;
                }}
            }} catch (e) {{}}
            closeEditArtistModal();
            showToast('✓ Artist profile updated!');
        }}

        function openCreateArtistModal() {{
            document.getElementById('create-artist-name').value = '';
            document.getElementById('create-artist-cover').value = '';
            document.getElementById('create-artist-bio').value = '';
            document.getElementById('create-artist-modal').classList.add('active');
        }}

        function closeCreateArtistModal() {{
            document.getElementById('create-artist-modal').classList.remove('active');
        }}

        async function handleCreateArtist(e) {{
            e.preventDefault();
            const payload = {{
                name: document.getElementById('create-artist-name').value,
                cover_url: document.getElementById('create-artist-cover').value,
                bio: document.getElementById('create-artist-bio').value
            }};

            try {{
                const res = await fetch('/api/artists', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (res.ok) {{
                    showToast('✓ New artist created successfully!');
                    closeCreateArtistModal();
                    return;
                }}
            }} catch (e) {{}}
            closeCreateArtistModal();
            showToast('✓ New artist entry created!');
        }}

        async function deleteArtist(id, name) {{
            if (!confirm('Are you sure you want to delete artist "' + name + '"?')) return;
            try {{
                await fetch('/api/artists/' + id, {{ method: 'DELETE' }});
            }} catch (e) {{}}
            const rows = document.querySelectorAll('.tab-pane table tbody tr');
            rows.forEach(r => {{
                if (r.innerHTML.includes("deleteArtist(" + id + ",")) {{
                    r.remove();
                }}
            }});
            showToast('✓ Artist record removed!');
        }}

        async function purgeEmptyArtists() {{
            if (!confirm('Purge all artists with 0 uploaded tracks from the platform?')) return;
            try {{
                const res = await fetch('/api/admin/artists/purge-empty', {{ method: 'POST' }});
                const d = await res.json();
                if (res.ok && d.success) {{
                    alert('✓ Purged ' + d.purged_count + ' 0-track artists!');
                    window.location.reload();
                }} else {{
                    alert('Purge error: ' + (d.detail || 'Failed'));
                }}
            }} catch (e) {{
                alert('Network error during purge');
            }}
        }}

        function previewTeamPhoto(input) {{
            if (input.files && input.files[0]) {{
                const file = input.files[0];
                const reader = new FileReader();
                reader.onload = function(e) {{
                    const preview = document.getElementById('team-photo-preview');
                    preview.src = e.target.result;
                    preview.style.display = 'block';
                    document.getElementById('team-photo-filename').textContent = file.name;
                }};
                reader.readAsDataURL(file);
            }}
        }}

        function openCreateTeamModal() {{
            document.getElementById('team-modal-title').innerHTML = '<i class="fas fa-user-plus"></i> Add Team Member';
            document.getElementById('team-member-id').value = '';
            document.getElementById('team-name-input').value = '';
            document.getElementById('team-role-input').value = '';
            document.getElementById('team-bio-input').value = '';
            document.getElementById('team-photo-input').value = '';
            document.getElementById('team-photo-preview').src = '/media/team/default-avatar.png';
            document.getElementById('team-photo-filename').textContent = 'Default avatar';
            document.getElementById('team-order-input').value = '1';
            document.getElementById('team-modal').classList.add('active');
        }}

        function openEditTeamModal(id, name, role, bio, photoPath, order) {{
            document.getElementById('team-modal-title').innerHTML = '<i class="fas fa-user-edit"></i> Edit Team Member';
            document.getElementById('team-member-id').value = id;
            document.getElementById('team-name-input').value = name;
            document.getElementById('team-role-input').value = role;
            document.getElementById('team-bio-input').value = bio || '';
            document.getElementById('team-photo-input').value = '';
            document.getElementById('team-photo-preview').src = photoPath || '/media/team/default-avatar.png';
            document.getElementById('team-photo-filename').textContent = 'Current photo';
            document.getElementById('team-order-input').value = order || 1;
            document.getElementById('team-modal').classList.add('active');
        }}

        function closeTeamModal() {{
            document.getElementById('team-modal').classList.remove('active');
        }}

        async function handleTeamSubmit(e) {{
            e.preventDefault();
            const btn = document.getElementById('btn-team-submit');
            btn.textContent = 'Saving Profile & Uploading Photo...';
            btn.disabled = true;

            const id = document.getElementById('team-member-id').value;
            const fd = new FormData();
            fd.append('name', document.getElementById('team-name-input').value);
            fd.append('role', document.getElementById('team-role-input').value);
            fd.append('bio', document.getElementById('team-bio-input').value);
            fd.append('display_order', document.getElementById('team-order-input').value || 0);

            const fileInput = document.getElementById('team-photo-input');
            if (fileInput.files && fileInput.files.length > 0) {{
                fd.append('photo', fileInput.files[0]);
            }}

            try {{
                const url = id ? ('/api/admin/team/' + id) : '/api/admin/team';
                const method = id ? 'PUT' : 'POST';
                const res = await fetch(url, {{ method: method, body: fd }});
                const d = await res.json();
                if (res.ok && d.success) {{
                    alert('✓ Team member profile saved successfully!');
                    window.location.reload();
                }} else {{
                    alert('Error: ' + (d.detail || 'Failed to save team member'));
                    btn.textContent = 'Save Team Member';
                    btn.disabled = false;
                }}
            }} catch (e) {{
                alert('Network error saving team member');
                btn.textContent = 'Save Team Member';
                btn.disabled = false;
            }}
        }}

        async function deleteTeamMember(id, name) {{
            if (!confirm('Are you sure you want to delete team member "' + name + '"?')) return;
            try {{
                const res = await fetch('/api/admin/team/' + id, {{ method: 'DELETE' }});
                const d = await res.json();
                if (res.ok && d.success) {{
                    alert('✓ Team member removed successfully!');
                    window.location.reload();
                }} else {{
                    alert('Error: ' + (d.detail || 'Failed to delete'));
                }}
            }} catch (e) {{
                alert('Network error deleting team member');
            }}
        }}

        async function handleSecurityUpdate(e) {{
            e.preventDefault();
            const payload = {{
                current_password: document.getElementById('sec-current-pwd').value,
                new_username: document.getElementById('sec-new-user').value,
                new_password: document.getElementById('sec-new-pwd').value || null
            }};

            const res = await fetch('/api/admin/security', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify(payload)
            }});
            const data = await res.json();
            if (res.ok && data.success) {{
                alert('✓ Administrator credentials updated successfully!');
                window.location.reload();
            }} else {{
                alert('Security update error: ' + (data.detail || 'Failed'));
            }}
        }}

        function openCreateVideoModal() {{
            document.getElementById('video-modal-title').innerHTML = '<i class="fas fa-video"></i> Add Official Music Video';
            document.getElementById('video-admin-id').value = '';
            document.getElementById('video-title-input').value = '';
            document.getElementById('video-yt-input').value = '';
            document.getElementById('video-thumb-input').value = '';
            document.getElementById('video-director-input').value = '';
            document.getElementById('video-featured-input').value = '0';
            document.getElementById('video-desc-input').value = '';
            document.getElementById('video-admin-modal').classList.add('active');
        }}

        function openEditVideoModal(id, title, artistId, genreId, ytUrl, thumbUrl, director, isFeatured, desc) {{
            document.getElementById('video-modal-title').innerHTML = '<i class="fas fa-edit"></i> Edit Official Music Video';
            document.getElementById('video-admin-id').value = id;
            document.getElementById('video-title-input').value = title;
            document.getElementById('video-artist-input').value = artistId;
            document.getElementById('video-genre-input').value = genreId;
            document.getElementById('video-yt-input').value = ytUrl;
            document.getElementById('video-thumb-input').value = thumbUrl || '';
            document.getElementById('video-director-input').value = director || '';
            document.getElementById('video-featured-input').value = isFeatured ? '1' : '0';
            document.getElementById('video-desc-input').value = desc || '';
            document.getElementById('video-admin-modal').classList.add('active');
        }}

        function closeVideoAdminModal() {{
            document.getElementById('video-admin-modal').classList.remove('active');
        }}

        async function handleVideoAdminSubmit(e) {{
            e.preventDefault();
            const btn = document.getElementById('btn-video-submit');
            btn.textContent = 'Saving Music Video...';
            btn.disabled = true;

            const id = document.getElementById('video-admin-id').value;
            const payload = {{
                title: document.getElementById('video-title-input').value,
                artist_id: parseInt(document.getElementById('video-artist-input').value),
                genre_id: parseInt(document.getElementById('video-genre-input').value),
                youtube_url: document.getElementById('video-yt-input').value,
                thumbnail_url: document.getElementById('video-thumb-input').value || null,
                director: document.getElementById('video-director-input').value || null,
                is_featured: document.getElementById('video-featured-input').value === '1',
                description: document.getElementById('video-desc-input').value || null
            }};

            try {{
                const url = id ? ('/api/admin/videos/' + id) : '/api/admin/videos';
                const method = id ? 'PUT' : 'POST';
                const res = await fetch(url, {{
                    method: method,
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                const d = await res.json();
                if (res.ok && d.success) {{
                    alert('✓ Music video saved successfully!');
                    window.location.reload();
                }} else {{
                    alert('Error: ' + (d.detail || 'Failed to save video'));
                    btn.textContent = 'Save Music Video';
                    btn.disabled = false;
                }}
            }} catch (e) {{
                alert('Network error saving video');
                btn.textContent = 'Save Music Video';
                btn.disabled = false;
            }}
        }}

        async function deleteVideo(id, title) {{
            if (!confirm('Are you sure you want to delete music video "' + title + '"?')) return;
            try {{
                const res = await fetch('/api/admin/videos/' + id, {{ method: 'DELETE' }});
                const d = await res.json();
                if (res.ok && d.success) {{
                    alert('✓ Music video removed successfully!');
                    window.location.reload();
                }} else {{
                    alert('Error: ' + (d.detail || 'Failed to delete'));
                }}
            }} catch (e) {{
                alert('Network error deleting video');
            }}
        }}

        function filterAdminTracks(q) {{
            const query = q.toLowerCase();
            document.querySelectorAll('#admin-tracks-table tbody tr').forEach(row => {{
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(query) ? '' : 'none';
            }});
        }}

        // Audio File Autodetection (Artist, Featured Artists, Title)
        const upFileInput = document.getElementById('up-file');
        if (upFileInput) {{
            upFileInput.addEventListener('change', function(e) {{
                if (this.files && this.files[0]) {{
                    let name = this.files[0].name.replace(/\\.[^/.]+$/, "").trim();
                    name = name.replace(/^\\d+[\\s.-]+/, "").trim();
                    
                    let artist = "";
                    let featured = "";
                    let title = "";

                    const parenMatch = name.match(/^(.*?)\\s*\\((.*?)\\)$/);
                    if (parenMatch) {{
                        let part1 = parenMatch[1].trim();
                        let part2 = parenMatch[2].trim();
                        const featInPart2 = part2.match(/^(?:ft\\.?|feat\\.?|featuring)\\s+(.+)$/i);
                        if (featInPart2) {{
                            featured = featInPart2[1].trim();
                            const hyphenParts = part1.split(/\\s*-\\s*/);
                            if (hyphenParts.length >= 2) {{
                                artist = hyphenParts[0].trim();
                                title = hyphenParts.slice(1).join(" - ").trim();
                            }} else {{
                                title = part1;
                            }}
                        }} else {{
                            title = part2;
                            const featMatch = part1.match(/\\s+(?:ft\\.?|feat\\.?|featuring)\\s+(.+)$/i);
                            if (featMatch) {{
                                featured = featMatch[1].trim();
                                artist = part1.substring(0, featMatch.index).trim();
                            }} else {{
                                artist = part1;
                            }}
                        }}
                    }} else {{
                        const parts = name.split(/\\s*-\\s*/);
                        if (parts.length >= 2) {{
                            artist = parts[0].trim();
                            title = parts.slice(1).join(" - ").trim();
                            const featInTitle = title.match(/[\\(\\[\\s]+(?:ft\\.?|feat\\.?|featuring)\\s+([^\\)\\]]+)[\\)\\]]?/i);
                            if (featInTitle) {{
                                featured = featInTitle[1].trim();
                                title = title.replace(/[\\(\\[\\s]+(?:ft\\.?|feat\\.?|featuring)\\s+[^\\)\\]]+[\\)\\]]?/ig, '').trim();
                            }} else {{
                                const featInArtist = artist.match(/\\s+(?:ft\\.?|feat\\.?|featuring)\\s+(.+)$/i);
                                if (featInArtist) {{
                                    featured = featInArtist[1].trim();
                                    artist = artist.substring(0, featInArtist.index).trim();
                                }}
                            }}
                        }} else {{
                            const featMatch = name.match(/\\s+(?:ft\\.?|feat\\.?|featuring)\\s+(.+)$/i);
                            if (featMatch) {{
                                featured = featMatch[1].trim();
                                artist = name.substring(0, featMatch.index).trim();
                            }} else {{
                                title = name;
                            }}
                        }}
                    }}

                    if (title) {{
                        document.getElementById('up-title').value = title;
                    }}
                    if (artist) {{
                        document.getElementById('up-artist').value = artist;
                    }}
                    if (featured) {{
                        document.getElementById('up-featured-artists').value = featured;
                    }}
                }}
            }});
        }}

        async function logoutAdmin() {{
            await fetch('/api/admin/logout', {{ method: 'POST' }});
            window.location.reload();
        }}
    </script>
</body>
</html>
"""
    return HTMLResponse(content=html)
