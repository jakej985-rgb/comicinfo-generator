import os
import shutil
import tempfile
import unittest
from cache.jobs import JobStore, STATUS_PENDING, STATUS_PROCESSING, STATUS_SUCCESS, STATUS_SKIPPED, STATUS_REVIEW

class TestJobStoreAndRestartSafety(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "jobs_test.db")
        self.sample_file = os.path.join(self.temp_dir, "Batman 001.cbz")
        with open(self.sample_file, "wb") as f:
            f.write(b"PK\x03\x04fakezipcontent")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_and_fetch_job(self):
        store = JobStore(db_path=self.db_path)
        job = store.create_job(self.sample_file)

        self.assertEqual(job["status"], STATUS_PENDING)
        self.assertEqual(job["path"], os.path.abspath(self.sample_file))

        fetched = store.fetch_next_pending_job()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], job["id"])
        self.assertEqual(fetched["status"], STATUS_PROCESSING)
        self.assertEqual(fetched["attempts"], 1)

    def test_restart_safety_resets_stale_processing_jobs(self):
        store = JobStore(db_path=self.db_path)
        job = store.create_job(self.sample_file)
        store.fetch_next_pending_job()  # Transition to PROCESSING

        # Verify status is PROCESSING
        current = store.get_job(job["id"])
        self.assertEqual(current["status"], STATUS_PROCESSING)

        # Simulate crash / reboot by re-instantiating JobStore
        restarted_store = JobStore(db_path=self.db_path)

        # Verify stale PROCESSING job was automatically reset to PENDING
        reset_job = restarted_store.get_job(job["id"])
        self.assertEqual(reset_job["status"], STATUS_PENDING)

if __name__ == "__main__":
    unittest.main()
