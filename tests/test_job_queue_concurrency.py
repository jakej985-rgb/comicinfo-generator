"""
Phase 48 — Durable Job Queue Concurrency Tests (Sections 48.1 - 48.5)

Tests:
1. Two workers claiming jobs without collision
2. Simultaneous concurrent claims by multiple threads (race safety)
3. Worker crash simulation with expired lease recovery
4. Active worker lease renewal
5. Maximum retry attempt limits (poison pill prevention)
6. Completed job lifecycle
7. Duplicate file submission deduplication
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


class TestJobQueueConcurrency(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "concurrency_jobs.db")
        self.store = JobStore(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 48.5.1: Two workers claiming distinct jobs
    def test_two_workers_claim_distinct_jobs(self):
        job1 = self.store.create_job(os.path.join(self.tmp, "comic1.cbz"))
        job2 = self.store.create_job(os.path.join(self.tmp, "comic2.cbz"))

        claim1 = self.store.claim_job(worker_id="worker_A")
        claim2 = self.store.claim_job(worker_id="worker_B")

        self.assertIsNotNone(claim1)
        self.assertIsNotNone(claim2)
        self.assertNotEqual(claim1["id"], claim2["id"])
        self.assertEqual(claim1["worker_id"], "worker_A")
        self.assertEqual(claim2["worker_id"], "worker_B")
        self.assertEqual(claim1["status"], STATUS_PROCESSING)
        self.assertEqual(claim2["status"], STATUS_PROCESSING)

    # 48.5.2: Simultaneous claims across multiple threads
    def test_simultaneous_claims_concurrency(self):
        num_jobs = 30
        job_ids = []
        for i in range(num_jobs):
            dummy_file = os.path.join(self.tmp, f"comic_{i:03d}.cbz")
            with open(dummy_file, "wb") as f:
                f.write(f"comic_{i}".encode("utf-8"))
            j = self.store.create_job(dummy_file)
            job_ids.append(j["id"])

        claimed_job_ids = []
        lock = threading.Lock()

        def worker_claim_loop(worker_name: str):
            while True:
                claimed = self.store.claim_job(worker_id=worker_name, lease_seconds=60)
                if not claimed:
                    break
                with lock:
                    claimed_job_ids.append((claimed["id"], worker_name))
                time.sleep(0.005)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_claim_loop, f"worker_{k}") for k in range(8)]
            for f in futures:
                f.result()

        # All 30 jobs claimed
        self.assertEqual(len(claimed_job_ids), num_jobs)
        # Exactly 0 duplicate claims across all threads
        unique_claimed = set(cid for cid, _ in claimed_job_ids)
        self.assertEqual(len(unique_claimed), num_jobs)

    # 48.5.3: Worker crash & Expired lease recovery
    def test_worker_crash_and_expired_lease_recovery(self):
        dummy_file = os.path.join(self.tmp, "crashed_worker_comic.cbz")
        with open(dummy_file, "wb") as f:
            f.write(b"content")

        job = self.store.create_job(dummy_file)
        # Claim with very short lease (1 second)
        claimed = self.store.claim_job(worker_id="crashed_worker", lease_seconds=1)
        self.assertEqual(claimed["worker_id"], "crashed_worker")

        # Worker B tries to claim immediately -> none available
        none_claimed = self.store.claim_job(worker_id="worker_B")
        self.assertIsNone(none_claimed)

        # Wait for lease to expire
        time.sleep(1.2)

        # Worker B claims now -> successfully reclaims expired lease
        reclaimed = self.store.claim_job(worker_id="worker_B", lease_seconds=60)
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["id"], job["id"])
        self.assertEqual(reclaimed["worker_id"], "worker_B")
        self.assertEqual(reclaimed["attempts"], 2)

    # 48.5.4: Active worker lease renewal
    def test_active_worker_lease_renewal(self):
        dummy_file = os.path.join(self.tmp, "renewal_comic.cbz")
        with open(dummy_file, "wb") as f:
            f.write(b"content")

        job = self.store.create_job(dummy_file)
        claimed = self.store.claim_job(worker_id="worker_A", lease_seconds=10)
        old_lease = claimed["lease_until"]

        time.sleep(0.1)
        renewed = self.store.renew_lease(job["id"], worker_id="worker_A", lease_seconds=100)
        self.assertTrue(renewed)

        updated_job = self.store.get_job(job["id"])
        self.assertGreater(updated_job["lease_until"], old_lease)

    # 48.5.5: Max attempts limit (poison pill protection)
    def test_max_attempts_limit_fails_poison_pill(self):
        dummy_file = os.path.join(self.tmp, "poison_pill.cbz")
        with open(dummy_file, "wb") as f:
            f.write(b"poison")

        job = self.store.create_job(dummy_file)
        
        # Claim 1 (lease 1 sec)
        c1 = self.store.claim_job(worker_id="worker_1", lease_seconds=1, max_attempts=2)
        self.assertIsNotNone(c1)
        self.assertEqual(c1["attempts"], 1)
        time.sleep(1.1)

        # Claim 2 (lease 1 sec)
        c2 = self.store.claim_job(worker_id="worker_2", lease_seconds=1, max_attempts=2)
        self.assertIsNotNone(c2)
        self.assertEqual(c2["attempts"], 2)
        time.sleep(1.1)

        # Claim 3 should fail because attempts >= max_attempts (2)
        c3 = self.store.claim_job(worker_id="worker_3", lease_seconds=10, max_attempts=2)
        self.assertIsNone(c3)

        # Job must be marked as FAILED with MAX_ATTEMPTS_EXCEEDED
        failed_job = self.store.get_job(job["id"])
        self.assertEqual(failed_job["status"], STATUS_FAILED)
        self.assertEqual(failed_job["error_code"], "MAX_ATTEMPTS_EXCEEDED")

    # 48.5.6: Completed job update
    def test_completed_job_status_update(self):
        dummy_file = os.path.join(self.tmp, "success_comic.cbz")
        with open(dummy_file, "wb") as f:
            f.write(b"success")

        job = self.store.create_job(dummy_file)
        claimed = self.store.claim_job(worker_id="worker_1")
        self.store.update_job_status(job["id"], status=STATUS_SUCCESS, provider="ComicVine", confidence=95.0)

        done_job = self.store.get_job(job["id"])
        self.assertEqual(done_job["status"], STATUS_SUCCESS)
        self.assertEqual(done_job["provider"], "ComicVine")
        self.assertEqual(done_job["confidence"], 95.0)
        self.assertIsNotNone(done_job["completed_at"])

    # 48.5.7: Duplicate file submission deduplication
    def test_duplicate_file_submission_deduplication(self):
        dummy_file = os.path.join(self.tmp, "dup_comic.cbz")
        with open(dummy_file, "wb") as f:
            f.write(b"same_content")

        job1 = self.store.create_job(dummy_file)
        job2 = self.store.create_job(dummy_file)

        self.assertEqual(job1["id"], job2["id"])
        all_jobs = self.store.list_jobs()
        self.assertEqual(len(all_jobs), 1)


if __name__ == "__main__":
    unittest.main()
