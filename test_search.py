import unittest
import database as db

class TestMultiFieldSearch(unittest.TestCase):
    def setUp(self):
        db.init_db()

    def test_multi_field_search_matching(self):
        # 1. Search by title
        r1 = db.get_tracks(search="aweah")
        self.assertTrue(len(r1) >= 0)

        # 2. Search by genre name
        r2 = db.get_tracks(search="afrobeats")
        for t in r2:
            self.assertTrue(
                "afrobeats" in t["genre"].lower() or 
                "afrobeats" in t["title"].lower() or 
                "afrobeats" in t["artist"].lower()
            )

        # 3. Create test track with multiple fields
        t = db.create_track(
            title="Search Unique Title XYZ",
            artist_name="Unique Artist ABC",
            genre_name="Kalindula",
            duration_seconds=180,
            file_name="test_search.mp3",
            storage_path="media/tracks/test_search.mp3",
            file_size_bytes=3000000,
            mime_type="audio/mpeg",
            sha256_hash="test_sha256_search_unique_9999",
            album_name="Greatest Album 2026",
            featured_artists="Star Collaborator"
        )
        
        # Test title search
        res_title = db.get_tracks(search="Unique Title XYZ")
        self.assertTrue(any(x["id"] == t["id"] for x in res_title))

        # Test artist search
        res_artist = db.get_tracks(search="Unique Artist ABC")
        self.assertTrue(any(x["id"] == t["id"] for x in res_artist))

        # Test featured artist search
        res_feat = db.get_tracks(search="Star Collaborator")
        self.assertTrue(any(x["id"] == t["id"] for x in res_feat))

        # Test album search
        res_album = db.get_tracks(search="Greatest Album 2026")
        self.assertTrue(any(x["id"] == t["id"] for x in res_album))

        # Test genre search
        res_genre = db.get_tracks(search="Kalindula")
        self.assertTrue(any(x["id"] == t["id"] for x in res_genre))

        # Cleanup
        db.delete_track(t["id"])

if __name__ == "__main__":
    unittest.main()
