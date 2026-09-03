# ============================================================================
# Zedhits Automated ID3 Tag & Embedded Artwork Extractor (Mutagen Engine)
# ============================================================================
import os
import re
import hashlib
from typing import Dict, Any, Optional

import mutagen
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
COVERS_DIR = os.path.join(BASE_DIR, "media", "covers")
os.makedirs(COVERS_DIR, exist_ok=True)

def parse_filename_fallback(filename: str) -> Dict[str, str]:
    """Fallback parser extracting artist, featured artists, and title (e.g. 'Dre Parker Ft Jay Wolf (The Debate).mp3')"""
    base = os.path.splitext(filename)[0].strip()
    # Remove leading numbers/track numbers like '01 - ' or '01. '
    base = re.sub(r'^\d+[\s.-]+', '', base).strip()
    
    artist = "Unknown Artist"
    title = base or "Untitled Track"
    featured = ""

    # Check for pattern like: "Artist Ft Feature (Title)" vs "Artist - Title (feat. Feature)"
    paren_match = re.search(r'^(.*?)\s*\((.*?)\)$', base)
    if paren_match:
        part1 = paren_match.group(1).strip()
        part2 = paren_match.group(2).strip()

        # Is part2 a featured artist tag? (e.g. feat. Towela)
        feat_in_part2 = re.search(r'^(?:ft\.?|feat\.?|featuring)\s+(.+)$', part2, re.IGNORECASE)
        if feat_in_part2:
            featured = feat_in_part2.group(1).strip()
            # Now parse part1 for artist - title
            hyphen_parts = re.split(r'\s*-\s*', part1, maxsplit=1)
            if len(hyphen_parts) == 2:
                artist = hyphen_parts[0].strip()
                title = hyphen_parts[1].strip()
            else:
                title = part1
        else:
            # part2 is the song title! (e.g. Dre Parker Ft Jay Wolf (The Debate))
            title = part2
            feat_match = re.search(r'\s+(?:ft\.?|feat\.?|featuring)\s+(.+)$', part1, re.IGNORECASE)
            if feat_match:
                featured = feat_match.group(1).strip()
                artist = part1[:feat_match.start()].strip()
            else:
                artist = part1
    else:
        # Check for hyphen separation "Artist - Title"
        parts = re.split(r'\s*-\s*', base, maxsplit=1)
        if len(parts) == 2:
            artist = parts[0].strip()
            title = parts[1].strip()
            
            # Check for feat in title (e.g. "Song (ft. Artist)" or "Song feat. Artist")
            feat_in_title = re.search(r'[\(\[\s]+(?:ft\.?|feat\.?|featuring)\s+([^\)\]]+)[\)\]]?', title, re.IGNORECASE)
            if feat_in_title:
                featured = feat_in_title.group(1).strip()
                title = re.sub(r'[\(\[\s]+(?:ft\.?|feat\.?|featuring)\s+[^\)\]]+[\)\]]?', '', title, flags=re.IGNORECASE).strip()
            else:
                # Check for feat in artist
                feat_in_artist = re.search(r'\s+(?:ft\.?|feat\.?|featuring)\s+(.+)$', artist, re.IGNORECASE)
                if feat_in_artist:
                    featured = feat_in_artist.group(1).strip()
                    artist = artist[:feat_in_artist.start()].strip()
        else:
            feat_match = re.search(r'\s+(?:ft\.?|feat\.?|featuring)\s+(.+)$', base, re.IGNORECASE)
            if feat_match:
                featured = feat_match.group(1).strip()
                artist = base[:feat_match.start()].strip()

    return {"artist": artist or "Unknown Artist", "title": title or "Untitled Track", "featured_artists": featured}

def extract_audio_metadata(file_path: str, original_filename: str = "") -> Dict[str, Any]:
    """
    Extracts complete ID3 metadata, technical properties, and embedded cover art.
    """
    filename_to_use = original_filename or os.path.basename(file_path)
    fallback = parse_filename_fallback(filename_to_use)

    metadata: Dict[str, Any] = {
        "title": fallback["title"],
        "artist": fallback["artist"],
        "featured_artists": fallback.get("featured_artists", ""),
        "album": "",
        "genre": "Afrobeats",
        "year": "",
        "duration_seconds": 210,
        "bitrate_kbps": 320,
        "sample_rate_hz": 44100,
        "cover_url": "",
        "has_embedded_cover": False,
        "extracted_tags": False
    }

    try:
        audio = mutagen.File(file_path, easy=True)
        raw_audio = mutagen.File(file_path)

        if audio is not None:
            metadata["extracted_tags"] = True

            # Extract Title
            if "title" in audio and audio["title"]:
                raw_title = str(audio["title"][0]).strip()
                metadata["title"] = raw_title
                # Check if feat is inside title
                feat_in_title = re.search(r'[\(\[\s]+(?:ft\.?|feat\.?|featuring)\s+([^\)\]]+)[\)\]]?', raw_title, re.IGNORECASE)
                if feat_in_title and not metadata["featured_artists"]:
                    metadata["featured_artists"] = feat_in_title.group(1).strip()
                    metadata["title"] = re.sub(r'[\(\[\s]+(?:ft\.?|feat\.?|featuring)\s+[^\)\]]+[\)\]]?', '', raw_title, flags=re.IGNORECASE).strip()

            # Extract Artist
            if "artist" in audio and audio["artist"]:
                raw_artist = str(audio["artist"][0]).strip()
                feat_in_artist = re.search(r'\s+(?:ft\.?|feat\.?|featuring)\s+(.+)$', raw_artist, re.IGNORECASE)
                if feat_in_artist:
                    metadata["artist"] = raw_artist[:feat_in_artist.start()].strip()
                    if not metadata["featured_artists"]:
                        metadata["featured_artists"] = feat_in_artist.group(1).strip()
                else:
                    metadata["artist"] = raw_artist
            # Extract Album
            if "album" in audio and audio["album"]:
                metadata["album"] = str(audio["album"][0]).strip()
            # Extract Genre
            if "genre" in audio and audio["genre"]:
                metadata["genre"] = str(audio["genre"][0]).strip()
            # Extract Date / Year
            if "date" in audio and audio["date"]:
                metadata["year"] = str(audio["date"][0]).strip()

            # Technical Properties
            if hasattr(audio, "info"):
                if hasattr(audio.info, "length") and audio.info.length:
                    metadata["duration_seconds"] = int(round(audio.info.length))
                if hasattr(audio.info, "bitrate") and audio.info.bitrate:
                    metadata["bitrate_kbps"] = int(round(audio.info.bitrate / 1000))
                if hasattr(audio.info, "sample_rate") and audio.info.sample_rate:
                    metadata["sample_rate_hz"] = int(audio.info.sample_rate)

        # Extract Embedded Cover Artwork
        cover_bytes: Optional[bytes] = None
        cover_ext = ".jpg"

        if raw_audio is not None:
            # 1. MP3 / ID3 APIC tags
            if hasattr(raw_audio, "tags") and raw_audio.tags:
                for key in raw_audio.tags.keys():
                    if key.startswith("APIC"):
                        apic_frame = raw_audio.tags[key]
                        cover_bytes = apic_frame.data
                        if "png" in apic_frame.mime.lower():
                            cover_ext = ".png"
                        break

            # 2. FLAC pictures
            if not cover_bytes and hasattr(raw_audio, "pictures") and raw_audio.pictures:
                pic = raw_audio.pictures[0]
                cover_bytes = pic.data
                if "png" in pic.mime.lower():
                    cover_ext = ".png"

            # 3. MP4 / M4A covr
            if not cover_bytes and hasattr(raw_audio, "tags") and raw_audio.tags and "covr" in raw_audio.tags:
                covr_list = raw_audio.tags["covr"]
                if covr_list:
                    cover_bytes = bytes(covr_list[0])

        if cover_bytes:
            cover_hash = hashlib.sha256(cover_bytes).hexdigest()
            cover_filename = f"{cover_hash}{cover_ext}"
            cover_storage_path = os.path.join(COVERS_DIR, cover_filename)

            if not os.path.exists(cover_storage_path):
                with open(cover_storage_path, "wb") as f:
                    f.write(cover_bytes)

            metadata["cover_url"] = f"/media/covers/{cover_filename}"
            metadata["has_embedded_cover"] = True

    except Exception as e:
        print(f"[Metadata Extractor] Note during extraction for {filename_to_use}: {e}")

    return metadata
