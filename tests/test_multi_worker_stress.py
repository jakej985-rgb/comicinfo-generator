"""
Phase 64 — Multi-Worker Stress Tests

Verifies:
1. 4 simultaneous workers processing 100 queued jobs with exactly-once processing guarantee.
2. 64.1 Worker crash: worker dies during lease; lease expires; job reclaimed and completed by new worker.
3. 64.2 Poison job: permanently failing archive retries up to max_attempts (3) then transitions to FAILED without infinite loop.
"""
import os
import shutil
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from cache.jobs import (
    JobStore,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_SUCCESS,
    STATUS_FAILED
)


class TestMultiWorkerStress(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "stress_jobs.db")
        self.store = JobStore(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_100_jobs_4_parallel_workers(self):
        """Phase 64: 4 parallel workers process 100 queued jobs with exactly-once processing."""
        num_jobs = 100
        num_workers = 4

        # Create 100 dummy files & jobs
        job_ids = []
        for i in range(num_jobs):
            file_path = os.path.join(self.tmp, f"comic_{i:04d}.cbz")
            with open(file_path, "wb") as f:
                f.write(f"comic_archive_data_{i}".encode("utf-8"))
            job = self.store.create_job(file_path)
            job_ids.append(job["id"])

        processed_record = []
        lock = threading.Lock()

        def worker_loop(worker_name: str):
            while True:
                claimed = self.store.claim_job(worker_id=worker_name, lease_seconds=30)
                if not claimed:
                    break

                job_id = claimed["id"]
                # Simulate work
                time.sleep(0.002)

                with lock:
                    processed_record.append((job_id, worker_name))

                # Update job to SUCCESS
                self.store.update_job_status(
                    job_id=job_id,
                    status=STATUS_SUCCESS,
                    provider="ComicVine",
                    confidence=95.0
                )

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_loop, f"worker-{k+1}") for k in range(num_workers)]
            for f in futures:
                f.result()

        # 1. Assert exactly 100 jobs were processed
        self.assertEqual(len(processed_record), num_jobs)

        # 2. Assert every unique job was processed exactly once (no duplicates)
        processed_job_ids = [jid for jid, _ in processed_record]
        self.assertEqual(len(set(processed_job_ids)), num_jobs)
        self.assertEqual(sorted(processed_job_ids), sorted(job_ids))

        # 3. Assert all jobs in DB are marked STATUS_SUCCESS with attempts == 1
        all_db_jobs = self.store.list_jobs(limit=200)
        self.assertEqual(len(all_db_jobs), num_jobs)
        for j in all_db_jobs:
            self.assertEqual(j["status"], STATUS_SUCCESS)
            self.assertEqual(j["attempts"], 1)

    def test_worker_crash_and_recovery_by_second_worker(self):
        """64.1: Worker crash leaves lease; lease expires; second worker reclaims and completes."""
        file_path = os.path.join(self.tmp, "crashed_worker_comic.cbz")
        with open(file_path, "wb") as f:
            f.write(b"crashed_data")

        job = self.store.create_job(file_path)

        # Worker 1 claims with a short 0.5s lease and then crashes/stops
        claim1 = self.store.claim_job(worker_id="worker-1", lease_seconds=0.5)
        self.assertIsNotNone(claim1)
        self.assertEqual(claim1["worker_id"], "worker-1")
        self.assertEqual(claim1["attempts"], 1)

        # Immediate attempt by worker-2 finds no pending jobs
        claim_immediate = self.store.claim_job(worker_id="worker-2", lease_seconds=10)
        self.assertIsNone(claim_immediate)

        # Wait for worker-1's lease to expire
        time.sleep(0.6)

        # Worker 2 claims the expired job
        claim2 = self.store.claim_job(worker_id="worker-2", lease_seconds=10)
        self.assertIsNotNone(claim2)
        self.assertEqual(claim2["id"], job["id"])
        self.assertEqual(claim2["worker_id"], "worker-2")
        self.assertEqual(claim2["attempts"], 2)

        # Worker 2 successfully finishes processing
        self.store.update_job_status(job["id"], status=STATUS_SUCCESS, provider="Kapowarr", confidence=90.0)

        final_job = self.store.get_job(job["id"])
        self.assertEqual(final_job["status"], STATUS_SUCCESS)
        self.assertEqual(final_job["attempts"], 2)

    def test_poison_job_three_attempts_and_failed_terminal_state(self):
        """64.2: Poison job attempts 1, 2, 3, then transitions to FAILED without infinite loop."""
        file_path = os.path.join(self.tmp, "poison_pill.cbz")
        with open(file_path, "wb") as f:
            f.write(b"corrupted_archive_data")

        job = self.store.create_job(file_path)

        # Attempt 1: Worker 1 claims with 0.3s lease, fails without completing
        c1 = self.store.claim_job(worker_id="worker-1", lease_seconds=0.3, max_attempts=3)
        self.assertIsNotNone(c1)
        self.assertEqual(c1["attempts"], 1)
        time.sleep(0.35)

        # Attempt 2: Worker 2 claims expired job, fails without completing
        c2 = self.store.claim_job(worker_id="worker-2", lease_seconds=0.3, max_attempts=3)
        self.assertIsNotNone(c2)
        self.assertEqual(c2["attempts"], 2)
        time.sleep(0.35)

        # Attempt 3: Worker 3 claims expired job, fails without completing
        c3 = self.store.claim_job(worker_id="worker-3", lease_seconds=0.3, max_attempts=3)
        self.assertIsNotNone(c3)
        self.assertEqual(c3["attempts"], 3)
        time.sleep(0.35)

        # Attempt 4: Worker 4 tries to claim -> must return None (attempts >= max_attempts)
        c4 = self.store.claim_job(worker_id="worker-4", lease_seconds=10, max_attempts=3)
        self.assertIsNone(c4)

        # Job must be in terminal FAILED state with MAX_ATTEMPTS_EXCEEDED
        failed_job = self.store.get_job(job["id"])
        self.assertEqual(failed_job["status"], STATUS_FAILED)
        self.assertEqual(failed_job["error_code"], "MAX_ATTEMPTS_EXCEEDED")
        self.assertEqual(failed_job["attempts"], 3)


if __name__ == "__main__":
    unittest.main()
