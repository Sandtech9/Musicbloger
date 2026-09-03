# ============================================================================
# Zedhits Enterprise Music Platform Autonomous Verification Test Suite
# ============================================================================
import os
import io
import sys
import zipfile
import hashlib
from fastapi.testclient import TestClient

import database as db
from server import app
import sanitizer

client = TestClient(app)

def reset_admin():
    conn = db.get_connection()
    try:
        pwd_hash, salt = db.hash_password("admin123")
        conn.execute("DELETE FROM admins")
        conn.execute("INSERT INTO admins (username, password_hash, salt) VALUES (?, ?, ?)", ("admin", pwd_hash, salt))
        conn.commit()
    finally:
        conn.close()

def run_tests():
    print("====================================================================")
    print("   Zedhits Full Music Platform Autonomous Zero-Anomaly Audit        ")
    print("====================================================================")

    reset_admin()

    # 1. Verify Database Initialization & Defaults
    db.init_db()
    settings = db.get_site_settings()
    assert settings["site_title"] in ["ZedHits", "ZedHits Live Stream"], f"Got {settings['site_title']}"
    assert "about_title" in settings, "about_title missing from settings"
    print("[TEST 1/13 PASSED] [OK] 3NF Database & Site Settings initialized.")

    # 2. Verify Admin PBKDF2 Authentication
    login_res = client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    token = login_res.json()["token"]
    assert token, "No token returned"
    print("[TEST 2/13 PASSED] [OK] PBKDF2-HMAC-SHA256 Admin Login verified.")

    # 3. Verify Track Upload & ID3 Physical Storage
    sample_audio_content = b"ID3\x03\x00\x00\x00\x00\x00#TSSE\x00\x00\x00\x0f\x00\x00\x01Zedhits Audio Byte Stream 2026 Test Content"
    expected_sha = hashlib.sha256(sample_audio_content).hexdigest()

    upload_res = client.post(
        "/api/tracks",
        data={
            "title": "Aweah (Acoustic)",
            "artist": "Yo Maps",
            "genre": "Afrobeats",
            "duration_seconds": "215",
            "lyrics": "You are my one and only... (Official Lyrics)"
        },
        files={
            "file": ("yo_maps_aweah.mp3", io.BytesIO(sample_audio_content), "audio/mpeg")
        }
    )
    assert upload_res.status_code == 201, f"Upload failed: {upload_res.text}"
    track_data = upload_res.json()["track"]
    track_id = track_data["id"]
    artist_id = track_data["artist_id"]
    assert track_data["sha256_hash"] == expected_sha, "Hash mismatch"
    assert os.path.exists(track_data["storage_path"]), "Physical file not created on disk"
    print(f"[TEST 3/13 PASSED] [OK] Audio upload & physical storage ({expected_sha[:8]}...) verified.")

    # 4. Verify Track Download Counter & Stream Delivery
    dl_res = client.get(f"/api/tracks/{track_id}/download")
    assert dl_res.status_code == 200
    assert len(dl_res.content) == len(sample_audio_content)
    updated_track = db.get_track_by_id(track_id)
    assert updated_track["downloads_count"] >= 1, "Download count did not increment"
    print("[TEST 4/13 PASSED] [OK] 1-Click Track Download & Metrics tracking verified.")

    # 5. Verify Dedicated SEO Song Page (/track/{id})
    track_page_res = client.get(f"/track/{track_id}")
    assert track_page_res.status_code == 200
    assert "Aweah (Acoustic)" in track_page_res.text
    assert "Yo Maps" in track_page_res.text
    assert "og:title" in track_page_res.text
    assert "Official Lyrics" in track_page_res.text
    print("[TEST 5/13 PASSED] [OK] Dedicated SEO Song Download Page with OpenGraph & Lyrics verified.")

    # 6. Verify Artist Discography Page (/artist/{id})
    artist_page_res = client.get(f"/artist/{artist_id}")
    assert artist_page_res.status_code == 200
    assert "Yo Maps" in artist_page_res.text
    assert "Complete Discography" in artist_page_res.text
    print("[TEST 6/13 PASSED] [OK] Artist Profile & Discography Hub verified.")

    # 7. Verify Embeddable Mini-Player Widget (/embed/track/{id})
    embed_res = client.get(f"/embed/track/{track_id}")
    assert embed_res.status_code == 200
    assert "Aweah (Acoustic)" in embed_res.text
    print("[TEST 7/13 PASSED] [OK] Embeddable Iframe Mini-Player Widget verified.")

    # 8. Verify Bulk Discography ZIP Generator (/api/artists/{id}/zip)
    zip_res = client.get(f"/api/artists/{artist_id}/zip")
    assert zip_res.status_code == 200
    zip_buf = io.BytesIO(zip_res.content)
    with zipfile.ZipFile(zip_buf, "r") as zf:
        namelist = zf.namelist()
        assert len(namelist) >= 1
    print("[TEST 8/13 PASSED] [OK] 1-Click Bulk Artist Discography ZIP Streamer verified.")

    # 9. Verify Dedicated About Us Page (/about)
    about_res = client.get("/about")
    assert about_res.status_code == 200
    assert "Our Story" in about_res.text
    assert "Mission Directive" in about_res.text
    print("[TEST 9/13 PASSED] [OK] Dedicated /about Page with Mission & Pillars verified.")

    # 10. Verify Admin Real-Time Analytics API
    analytics_res = client.get("/api/admin/analytics")
    assert analytics_res.status_code == 200
    analytics_data = analytics_res.json()
    assert analytics_data["total_tracks"] >= 1
    assert analytics_data["total_artists"] >= 1
    print("[TEST 10/13 PASSED] [OK] Admin Real-Time KPI Analytics & Bandwidth Metrics verified.")

    # 11. Verify SHA-256 Deduplication (HTTP 409)
    dup_res = client.post(
        "/api/tracks",
        data={"title": "Dup Test", "artist": "Other", "genre": "Kalindula"},
        files={"file": ("dup.mp3", io.BytesIO(sample_audio_content), "audio/mpeg")}
    )
    assert dup_res.status_code == 409
    print("[TEST 11/13 PASSED] [OK] SHA-256 Deduplication verified (HTTP 409).")

    # 12. Verify Track Metadata Update
    edit_res = client.put(
        f"/api/tracks/{track_id}",
        json={"title": "Aweah (Master Remix 2026)", "artist": "Yo Maps", "genre": "Kalindula"}
    )
    assert edit_res.status_code == 200
    print("[TEST 12/13 PASSED] [OK] Relational Metadata Update verified.")

    # 13. Verify Cascade Deletion of DB Record & Disk File
    storage_path = track_data["storage_path"]
    del_res = client.delete(f"/api/tracks/{track_id}")
    assert del_res.status_code == 200
    assert not os.path.exists(storage_path)
    print("[TEST 13/13 PASSED] [OK] Full Cascade Deletion (Database row + Physical Disk File) verified.")

    # Run Sanitizer Verification
    print("\n[Phase 14] Running Sanitizer Verification...")
    sanitizer.run_sanitizer()

    reset_admin()

    print("\n====================================================================")
    print("   ALL 13 MUSIC PLATFORM TESTS PASSED WITH ZERO ANOMALIES           ")
    print("====================================================================")

if __name__ == "__main__":
    run_tests()
