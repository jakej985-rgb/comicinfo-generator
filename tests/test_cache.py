import unittest
import os
import tempfile
from cache.db import CacheManager
from cache.tracker import calculate_sha256, is_file_unchanged, mark_file_processed
from models.comic import Comic

class TestCache(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_cache.db")
        self.cache_mgr = CacheManager(self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_issue_caching(self):
        comic = Comic(title="Batman #1", series="Batman", number="1", publisher="DC Comics")
        self.cache_mgr.save_cached_issue("CV", "4000-12345", comic)
        
        cached = self.cache_mgr.get_cached_issue("CV", "4000-12345")
        self.assertIsNotNone(cached)
        self.assertEqual(cached.title, "Batman #1")
        self.assertEqual(cached.publisher, "DC Comics")

    def test_file_hash_tracking(self):
        test_file = os.path.join(self.tmp_dir.name, "test_comic.cbz")
        with open(test_file, "w") as f:
            f.write("mock comic content 123")

        self.assertFalse(is_file_unchanged(test_file, self.cache_mgr))
        
        mark_file_processed(test_file, self.cache_mgr, provider_used="Kapowarr")
        self.assertTrue(is_file_unchanged(test_file, self.cache_mgr))

        # Modify file
        with open(test_file, "a") as f:
            f.write("modified content")

        self.assertFalse(is_file_unchanged(test_file, self.cache_mgr))

if __name__ == "__main__":
    unittest.main()
