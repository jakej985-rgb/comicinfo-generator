import os
import time
import tempfile
import unittest
from models.comic import Comic
from cache.db import CacheManager, CACHE_SCHEMA_VERSION, TTL_ISSUE


class TestCachePhase30And31(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_cache.db")
        self.cache = CacheManager(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def _make_comic(self, title="Batman #1", series="Batman", number="1",
                    publisher="DC Comics", year=2016):
        return Comic(title=title, series=series, number=number,
                     publisher=publisher, year=year)

    # --- Phase 30: Schema version & TTL stored per record ---

    def test_issue_cache_stores_schema_version(self):
        comic = self._make_comic()
        self.cache.save_cached_issue("ComicVine", "cv-123", comic)

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT schema_version, expires_at, source_hash FROM issue_cache "
            "WHERE provider='ComicVine' AND issue_id='cv-123';"
        ).fetchone()
        conn.close()

        self.assertEqual(row["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertGreater(row["expires_at"], int(time.time()))
        self.assertIsNotNone(row["source_hash"])

    def test_series_cache_stores_schema_version(self):
        self.cache.save_cached_series("ComicVine", "vol-456", name="Batman",
                                      year=2016, publisher="DC Comics",
                                      data={"id": "vol-456"})
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT schema_version, expires_at FROM series_cache "
            "WHERE provider='ComicVine' AND series_id='vol-456';"
        ).fetchone()
        conn.close()

        self.assertEqual(row["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertGreater(row["expires_at"], int(time.time()))

    def test_url_cache_roundtrip(self):
        """Phase 30: URL cache stores and retrieves data correctly."""
        data = {"html": "<html>Batman</html>", "status": 200}
        self.cache.save_cached_url("ComicVine", "https://comicvine.gamespot.com/batman", data)
        result = self.cache.get_cached_url("ComicVine", "https://comicvine.gamespot.com/batman")
        self.assertEqual(result["status"], 200)

    # --- Phase 31: Cache invalidation ---

    def test_expired_issue_returns_none(self):
        """Phase 31: Entry past its TTL must not be returned."""
        comic = self._make_comic()
        self.cache.save_cached_issue("ComicVine", "cv-expired", comic)

        # Force expiry by zeroing expires_at directly
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE issue_cache SET expires_at = 1 WHERE issue_id = 'cv-expired';")
        conn.commit()
        conn.close()

        result = self.cache.get_cached_issue("ComicVine", "cv-expired")
        self.assertIsNone(result)

    def test_schema_version_mismatch_returns_none(self):
        """Phase 31: Stale schema_version must invalidate the entry."""
        comic = self._make_comic()
        self.cache.save_cached_issue("ComicVine", "cv-stale", comic)

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE issue_cache SET schema_version = '1.0' WHERE issue_id = 'cv-stale';"
        )
        conn.commit()
        conn.close()

        result = self.cache.get_cached_issue("ComicVine", "cv-stale")
        self.assertIsNone(result)

    def test_manual_invalidate_issue(self):
        """Phase 31: invalidate_issue() forces expires_at=0 so next read returns None."""
        comic = self._make_comic()
        self.cache.save_cached_issue("ComicVine", "cv-manualrefresh", comic)

        # Confirm it's cached
        self.assertIsNotNone(self.cache.get_cached_issue("ComicVine", "cv-manualrefresh"))

        # Force-invalidate
        self.cache.invalidate_issue("ComicVine", "cv-manualrefresh")

        # Must be None now
        self.assertIsNone(self.cache.get_cached_issue("ComicVine", "cv-manualrefresh"))

    def test_purge_expired_removes_stale_entries(self):
        """Phase 31: purge_expired() removes rows whose expires_at has passed."""
        comic = self._make_comic()
        self.cache.save_cached_issue("ComicVine", "cv-todelete", comic)

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE issue_cache SET expires_at = 1 WHERE issue_id = 'cv-todelete';")
        conn.commit()
        conn.close()

        deleted = self.cache.purge_expired()
        self.assertGreaterEqual(deleted, 1)

    def test_invalidate_all_for_schema_version(self):
        """Phase 31: Purge all entries of a specific old schema_version."""
        comic = self._make_comic()
        self.cache.save_cached_issue("ComicVine", "cv-oldschema", comic)

        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE issue_cache SET schema_version = '1.9' WHERE issue_id = 'cv-oldschema';"
        )
        conn.commit()
        conn.close()

        self.cache.invalidate_all_for_schema_version("1.9")
        result = self.cache.get_cached_issue("ComicVine", "cv-oldschema")
        self.assertIsNone(result)

    def test_stats_include_schema_version(self):
        stats = self.cache.get_stats()
        self.assertIn("schema_version", stats)
        self.assertEqual(stats["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertIn("urls_cached", stats)


if __name__ == "__main__":
    unittest.main()
