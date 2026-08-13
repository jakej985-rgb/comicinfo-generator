import os
import tempfile
import unittest
from cache.jobs import JobStore, STATUS_PENDING
from cache.db import CacheManager
from cache.tracker import mark_file_processed
from automation.watcher import ComicFileEventHandler

class TestDeduplicationAndWatcher(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.jobs_db = os.path.join(self.temp_dir, "jobs_dedup.db")
        self.cache_db = os.path.join(self.temp_dir, "cache_dedup.db")
        self.sample_file = os.path.join(self.temp_dir, "Batman 001.cbz")

        with open(self.sample_file, "wb") as f:
            f.write(b"PK\x03\x04initial_file_bytes")

    def tearDown(self):
        if os.path.exists(self.sample_file):
            os.remove(self.sample_file)
        if os.path.exists(self.jobs_db):
            os.remove(self.jobs_db)
        if os.path.exists(self.cache_db):
            os.remove(self.cache_db)
        os.rmdir(self.temp_dir)

    def test_job_deduplication(self):
        store = JobStore(db_path=self.jobs_db)

        # First job creation
        job1 = store.create_job(self.sample_file)
        self.assertEqual(job1["status"], STATUS_PENDING)

        # Second job creation with same file and same SHA256 -> must return existing job1
        job2 = store.create_job(self.sample_file)
        self.assertEqual(job1["id"], job2["id"])

        # Modify file bytes (different SHA256) -> must create new job
        with open(self.sample_file, "wb") as f:
            f.write(b"PK\x03\x04modified_file_bytes_different")

        job3 = store.create_job(self.sample_file)
        self.assertNotEqual(job1["id"], job3["id"])

    def test_watcher_ignores_self_modified_file(self):
        cache_mgr = CacheManager(db_path=self.cache_db)
        # Mark file as processed (stores its current SHA256)
        mark_file_processed(self.sample_file, cache_mgr)

        triggered = []
        handler = ComicFileEventHandler(
            cache_mgr=cache_mgr,
            on_file_changed=lambda path: triggered.append(path),
            log_callback=lambda msg: None
        )

        class DummyEvent:
            is_directory = False
            src_path = self.sample_file

        handler.on_modified(DummyEvent())
        # Should NOT trigger on_file_changed because hash matches known state!
        self.assertEqual(len(triggered), 0)

if __name__ == "__main__":
    unittest.main()
