import os
import unittest
import metadata_extractor
import database as db

class TestFeaturedArtists(unittest.TestCase):
    def test_filename_fallback_parsing(self):
        # Test case from user's screenshot: "Dre Paker Ft Jay Wolf (The Debate).mp3"
        r1 = metadata_extractor.parse_filename_fallback("Dre Paker Ft Jay Wolf (The Debate).mp3")
        self.assertEqual(r1["artist"], "Dre Paker")
        self.assertEqual(r1["featured_artists"], "Jay Wolf")
        self.assertEqual(r1["title"], "The Debate")

        # Test case: "Yo Maps ft. Fally Ipupa - Aweah.mp3"
        r2 = metadata_extractor.parse_filename_fallback("Yo Maps ft. Fally Ipupa - Aweah.mp3")
        self.assertEqual(r2["artist"], "Yo Maps")
        self.assertEqual(r2["featured_artists"], "Fally Ipupa")
        self.assertEqual(r2["title"], "Aweah")

        # Test case: "Chef 187 - Sensei Flow (feat. Towela).mp3"
        r3 = metadata_extractor.parse_filename_fallback("Chef 187 - Sensei Flow (feat. Towela).mp3")
        self.assertEqual(r3["artist"], "Chef 187")
        self.assertEqual(r3["featured_artists"], "Towela")
        self.assertEqual(r3["title"], "Sensei Flow")

        # Test simple track without features
        r4 = metadata_extractor.parse_filename_fallback("Macky 2 - Olijaba.mp3")
        self.assertEqual(r4["artist"], "Macky 2")
        self.assertEqual(r4["featured_artists"], "")
        self.assertEqual(r4["title"], "Olijaba")

    def test_database_featured_artists(self):
        db.init_db()
        # Create test track with featured artist
        t = db.create_track(
            title="The Debate",
            artist_name="Dre Parker",
            genre_name="Zed Hip Hop",
            duration_seconds=210,
            file_name="dre_test.mp3",
            storage_path="media/tracks/test_dre.mp3",
            file_size_bytes=4000000,
            mime_type="audio/mpeg",
            sha256_hash="test_sha256_dre_parker_123456",
            featured_artists="Jay Wolf"
        )
        self.assertIsNotNone(t)
        self.assertEqual(t["featured_artists"], "Jay Wolf")

        # Retrieve track
        fetched = db.get_track_by_id(t["id"])
        self.assertEqual(fetched["featured_artists"], "Jay Wolf")

        # Update track
        updated = db.update_track(t["id"], featured_artists="Jay Wolf, Towela")
        self.assertEqual(updated["featured_artists"], "Jay Wolf, Towela")

        # Search tracks
        search_res = db.get_tracks(search="Towela")
        self.assertTrue(any(x["id"] == t["id"] for x in search_res))

        # Cleanup
        db.delete_track(t["id"])

if __name__ == "__main__":
    unittest.main()
