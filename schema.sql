-- ============================================================================
-- Zedhits Database Architecture (3NF Relational SQLite Schema)
-- Dynamic CMS & Full UI Content Parity
-- ============================================================================
PRAGMA foreign_keys = ON;

-- 1. Admins Table
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Site Settings Table (Dynamic CMS Key-Value Store)
CREATE TABLE IF NOT EXISTS site_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 3. Artists Table
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    slug TEXT NOT NULL UNIQUE,
    bio TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Genres Table
CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    slug TEXT NOT NULL UNIQUE
);

-- 5. Tracks Table (Normalized Relational Model with ID3 Metadata & Metrics)
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist_id INTEGER NOT NULL REFERENCES artists(id) ON DELETE RESTRICT,
    featured_artists TEXT DEFAULT '',
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE RESTRICT,
    album_name TEXT DEFAULT '',
    lyrics TEXT DEFAULT '',
    duration_seconds INTEGER DEFAULT 0,
    bitrate_kbps INTEGER DEFAULT 320,
    cover_url TEXT DEFAULT '',
    plays_count INTEGER DEFAULT 0,
    downloads_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. Media Files Table (Physical Integrity & SHA-256 Deduplication)
CREATE TABLE IF NOT EXISTS media_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL UNIQUE REFERENCES tracks(id) ON DELETE CASCADE,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    sha256_hash TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist_id);
CREATE INDEX IF NOT EXISTS idx_tracks_genre ON tracks(genre_id);
CREATE INDEX IF NOT EXISTS idx_tracks_created ON tracks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_media_sha256 ON media_files(sha256_hash);

-- Pre-seed Genres
INSERT OR IGNORE INTO genres (name, slug) VALUES 
('Afrobeats', 'afrobeats'),
('Dancehall', 'dancehall'),
('Gospel', 'gospel'),
('Kalindula', 'kalindula'),
('Zed Hip Hop', 'zed-hip-hop'),
('RnB', 'rnb'),
('Pop', 'pop'),
('Others', 'others');

-- Pre-seed Site Settings (Comprehensive Defaults)
INSERT OR IGNORE INTO site_settings (key, value) VALUES 
('site_title', 'ZedHits'),
('nav_logo_text', 'ZedHits'),
('tagline', 'Download The Latest Zambian Music In 2026'),
('hero_title', 'Download The Latest Zambian Music In 2026'),
('hero_subtitle', 'The Pulse of Zambian & African Music Streaming & Studio Master MP3 Downloads'),
('favicon_url', ''),
('logo_url', ''),
('accent_color', '#06801e'),
('bg_base_color', '#f7f8f8'),
('card_surface_color', '#ffffff'),
('text_primary_color', '#2c2f34'),
('banner_active', 'true'),
('banner_message', 'Are you an Artist or Producer? Get your song uploaded & promoted on ZedHits!'),
('banner_type', 'promotional'),
('banner_btn_text', 'Chat WhatsApp'),
('banner_btn_link', ''),
('allow_downloads', 'true'),
('show_play_counts', 'true'),
('show_release_dates', 'true'),
('stream_quality_label', '320k HD'),
('default_sort_mode', 'latest'),
('empty_state_msg', 'No Songs Found in this Selection. Select another genre or explore the latest releases.'),
('section_latest_title', 'The Latest'),
('section_trending_title', 'TRENDING'),
('section_artists_title', 'ARTISTS'),
('contact_whatsapp', '+260970000000'),
('contact_phone', '+260970000000'),
('contact_whatsapp_msg', 'Hello ZedHits, I want to submit my song for upload and promotion.'),
('social_facebook', 'https://facebook.com'),
('social_twitter', 'https://x.com'),
('social_instagram', 'https://instagram.com'),
('social_youtube', 'https://youtube.com'),
('contact_email', 'support@zedhits.com'),
('about_title', 'About ZedHits'),
('about_description', 'ZedHits is Zambia''s premier autonomous music streaming and digital audio distribution platform. Founded with a vision to empower Zambian and African artists, ZedHits bridges the gap between creative talent and global music enthusiasts with studio-master quality audio, instant discography archives, and high-speed distribution.'),
('about_mission', 'Empowering African musical heritage through state-of-the-art streaming infrastructure and direct artist-to-fan discovery.'),
('about_stats_artists', '500+'),
('about_stats_streams', '1.2M+'),
('about_stats_quality', '320 kbps HD'),
('footer_text', '© 2026 ZedHits.com - Download The Latest Zambian Music In 2026. All Rights Reserved.');

-- 8. Team Members Table (About Us Leadership & Profiles)
CREATE TABLE IF NOT EXISTS team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    bio TEXT DEFAULT '',
    photo_path TEXT DEFAULT '/media/team/default-avatar.png',
    social_links TEXT DEFAULT '{}',
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 9. Music Videos Table
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
);
CREATE INDEX IF NOT EXISTS idx_videos_artist ON videos(artist_id);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC);
