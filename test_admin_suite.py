import os
import io
import unittest
from fastapi.testclient import TestClient
from server import app
import database as db

class TestAdminPanelComplete(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        db.init_db()

    def test_01_unauthenticated_admin_page(self):
        """Visiting /admin without session cookie renders login screen"""
        res = self.client.get("/admin")
        self.assertEqual(res.status_code, 200)
        self.assertIn("PBKDF2 Master Access Verification", res.text)
        self.assertIn("Admin Authentication", res.text)

    def test_02_admin_login_and_session(self):
        """Test admin login with wrong and correct credentials"""
        # Bad login
        res_bad = self.client.post("/api/admin/login", json={"username": "admin", "password": "wrongpassword"})
        self.assertEqual(res_bad.status_code, 401)

        # Good login
        res_good = self.client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        self.assertEqual(res_good.status_code, 200)
        self.assertTrue(res_good.json().get("success"))
        self.assertIn("zedhits_admin_session", res_good.cookies)

        # Access /admin with cookie
        res_admin = self.client.get("/admin", cookies=res_good.cookies)
        self.assertEqual(res_admin.status_code, 200)
        self.assertIn("Admin Dashboard & CMS Control", res_admin.text)
        self.assertIn("Brand Identity & Public Copy Settings", res_admin.text)
        self.assertIn("Music Pool & Tracks", res_admin.text)
        self.assertIn("Official Music Videos Pool", res_admin.text)
        self.assertIn("Executive & Creative Team", res_admin.text)

    def test_03_cms_settings_update(self):
        """Test updating site settings across various CMS sections"""
        login_res = self.client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        cookies = login_res.cookies

        payload = {
            "site_title": "ZedHits",
            "hero_title": "Download The Latest Zambian Music In 2026",
            "accent_color": "#06801e",
            "banner_active": "true",
            "banner_message": "Are you an Artist or Producer? Get your song uploaded & promoted on ZedHits!",
            "allow_downloads": "true",
            "contact_whatsapp": "+260970000000",
            "about_title": "About ZedHits",
            "about_mission": "Empowering African musical heritage through state-of-the-art streaming infrastructure."
        }
        res = self.client.post("/api/admin/settings", json=payload, cookies=cookies)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("success"))

        # Verify persisted in database
        settings = db.get_site_settings()
        self.assertEqual(settings["site_title"], "ZedHits")
        self.assertEqual(settings["accent_color"], "#06801e")
        self.assertEqual(settings["about_title"], "About ZedHits")

    def test_04_team_member_lifecycle(self):
        """Test complete CRUD for Executive & Creative Team members"""
        login_res = self.client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        cookies = login_res.cookies

        # 1. Create team member
        create_res = self.client.post(
            "/api/admin/team",
            data={
                "name": "Chanda Mwanza",
                "role": "Head of Artist Relations",
                "bio": "Managing top tier Zambian recording artists and licensing.",
                "display_order": "1"
            },
            cookies=cookies
        )
        self.assertEqual(create_res.status_code, 200)
        member = create_res.json().get("member")
        self.assertIsNotNone(member)
        member_id = member["id"]

        # 2. Update team member
        update_res = self.client.put(
            f"/api/admin/team/{member_id}",
            data={
                "name": "Chanda Mwanza (Updated)",
                "role": "Chief Operating Officer",
                "bio": "Directing artist management and national audio distribution.",
                "display_order": "2"
            },
            cookies=cookies
        )
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.json()["member"]["name"], "Chanda Mwanza (Updated)")

        # 3. Delete team member
        del_res = self.client.delete(f"/api/admin/team/{member_id}", cookies=cookies)
        self.assertEqual(del_res.status_code, 200)

    def test_05_music_videos_lifecycle(self):
        """Test complete CRUD for Music Videos Hub"""
        login_res = self.client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        cookies = login_res.cookies

        # 1. Create video
        genres = db.get_genres()
        artists = db.get_artists()
        g_id = genres[0]["id"] if genres else 1
        a_id = artists[0]["id"] if artists else 1

        v_res = self.client.post(
            "/api/admin/videos",
            json={
                "title": "Aweah Official HD Video",
                "artist_id": a_id,
                "genre_id": g_id,
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "director": "Director Lo",
                "description": "The official visuals for Aweah.",
                "is_featured": True
            },
            cookies=cookies
        )
        self.assertEqual(v_res.status_code, 200)
        video = v_res.json().get("video")
        self.assertIsNotNone(video)
        video_id = video["id"]

        # 2. Update video
        v_up_res = self.client.put(
            f"/api/admin/videos/{video_id}",
            json={
                "title": "Aweah (4K Ultra HD Visuals)",
                "artist_id": a_id,
                "genre_id": g_id,
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "director": "Director Lo & Team",
                "description": "Updated description in 4K.",
                "is_featured": False
            },
            cookies=cookies
        )
        self.assertEqual(v_up_res.status_code, 200)
        self.assertEqual(v_up_res.json()["video"]["title"], "Aweah (4K Ultra HD Visuals)")

        # 3. Delete video
        v_del_res = self.client.delete(f"/api/admin/videos/{video_id}", cookies=cookies)
        self.assertEqual(v_del_res.status_code, 200)

    def test_06_artist_crud(self):
        """Test verified artists creation, update, and purge"""
        login_res = self.client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        cookies = login_res.cookies

        # Create artist
        a_res = self.client.post(
            "/api/artists",
            json={"name": "Test Artist Admin 2026", "bio": "Bio for testing", "cover_url": ""},
            cookies=cookies
        )
        self.assertEqual(a_res.status_code, 200)
        artist = a_res.json().get("artist")
        a_id = artist["id"]

        # Update artist
        up_res = self.client.put(
            f"/api/artists/{a_id}",
            json={"name": "Test Artist Admin 2026 Updated", "bio": "Updated bio details", "cover_url": ""},
            cookies=cookies
        )
        self.assertEqual(up_res.status_code, 200)

        # Delete artist
        del_res = self.client.delete(f"/api/artists/{a_id}", cookies=cookies)
        self.assertEqual(del_res.status_code, 200)

    def test_07_track_upload_edit_delete(self):
        """Test track upload, edit with featured artists, and cascade deletion"""
        login_res = self.client.post("/api/admin/login", json={"username": "admin", "password": "admin123"})
        cookies = login_res.cookies

        # Upload track
        fake_audio = io.BytesIO(b"ID3\x03\x00\x00\x00\x00\x00#TIT2\x00\x00\x00\x07\x00\x00\x00Test TrackAudioDataUnique999")
        up_res = self.client.post(
            "/api/tracks",
            files={"file": ("test_admin_track.mp3", fake_audio, "audio/mpeg")},
            data={
                "title": "Admin Test Track",
                "artist": "Macky 2",
                "featured_artists": "Towela",
                "genre": "Afrobeats"
            },
            cookies=cookies
        )
        self.assertEqual(up_res.status_code, 201)
        track = up_res.json()["track"]
        t_id = track["id"]
        self.assertEqual(track["featured_artists"], "Towela")

        # Edit track
        edit_res = self.client.put(
            f"/api/tracks/{t_id}",
            json={
                "title": "Admin Test Track (Remix)",
                "artist": "Macky 2",
                "featured_artists": "Towela, Jay Wolf",
                "genre": "Afrobeats",
                "bitrate_kbps": 320
            },
            cookies=cookies
        )
        self.assertEqual(edit_res.status_code, 200)
        self.assertEqual(edit_res.json()["track"]["title"], "Admin Test Track (Remix)")
        self.assertEqual(edit_res.json()["track"]["featured_artists"], "Towela, Jay Wolf")

        # Delete track (Cascade purge)
        del_res = self.client.delete(f"/api/tracks/{t_id}", cookies=cookies)
        self.assertEqual(del_res.status_code, 200)

if __name__ == "__main__":
    unittest.main()
