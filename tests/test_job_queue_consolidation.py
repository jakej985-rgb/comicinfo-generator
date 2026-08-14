"""
tests/test_job_queue_consolidation.py — Phase 85: Job and Queue State Consolidation Tests

Verifies:
1. 85.1: JobStore is authoritative for processing state (DISCOVERED, QUEUED, PROCESSING, COMPLETED, FAILED, RETRYING, REVIEW).
2. 85.2: Hash Tracker acts purely as idempotency data.
3. 85.3: ProcessingQueue performs execution lifecycle (claim -> execute -> report -> complete) against JobStore.
"""

import os
import shutil
import tempfile
import time
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from config import Config
from cache.db import CacheManager
from cache.jobs import (
    JobStore,
    STATUS_DISCOVERED,
    STATUS_QUEUED,
    STATUS_PROCESSING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RETRYING,
    STATUS_REVIEW,
    STATUS_SKIPPED
)
from cache.tracker import is_file_unchanged, mark_file_processed, calculate_sha256
from automation.queue import ProcessingQueue, ProcessingItem
from models.comic import Comic


class TestJobQueueStateConsolidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase85_jobs_")
        self.db_path = os.path.join(self.tmp, "jobs.db")
        self.cache_path = os.path.join(self.tmp, "cache.db")
        self.cfg = Config()
        self.cfg.cache.db_path = self.cache_path
        self.cache_mgr = CacheManager(self.cache_path)
        self.job_store = JobStore(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_sample_cbz(self, filename: str) -> str:
        path = os.path.join(self.tmp, filename)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("001.jpg", b"fake_image_data_here")
        return path

    # ------------------------------------------------------------------ #
    # 85.1: JobStore Authoritative for Processing State                  #
    # ------------------------------------------------------------------ #
    def test_85_1_job_store_authoritative_lifecycle_states(self):
        """85.1: Verifies all canonical states: DISCOVERED, QUEUED, PROCESSING, COMPLETED, FAILED, RETRYING, REVIEW."""
        cbz = self._create_sample_cbz("Batman #001 (2016).cbz")
        
        # 1. DISCOVERED
        job = self.job_store.mark_discovered(cbz)
        self.assertEqual(job["status"], STATUS_DISCOVERED)
        job_id = job["id"]

        # 2. QUEUED
        self.job_store.mark_queued(job_id)
        self.assertEqual(self.job_store.get_job(job_id)["status"], STATUS_QUEUED)

        # 3. PROCESSING (Claim)
        claimed = self.job_store.claim_job(worker_id="worker-1")
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["id"], job_id)
        self.assertEqual(claimed["status"], STATUS_PROCESSING)
        self.assertEqual(claimed["worker_id"], "worker-1")

        # 4. RETRYING
        self.job_store.mark_retrying(job_id, error_code="HTTP_429", error_message="Rate limited")
        self.assertEqual(self.job_store.get_job(job_id)["status"], STATUS_RETRYING)
        self.assertEqual(self.job_store.get_job(job_id)["error_code"], "HTTP_429")

        # Re-claim from RETRYING
        reclaimed = self.job_store.claim_job(worker_id="worker-2")
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["id"], job_id)
        self.assertEqual(reclaimed["status"], STATUS_PROCESSING)

        # 5. REVIEW
        self.job_store.mark_review(job_id, confidence=65.0, error_message="Ambiguous series name")
        self.assertEqual(self.job_store.get_job(job_id)["status"], STATUS_REVIEW)
        self.assertEqual(self.job_store.get_job(job_id)["confidence"], 65.0)

        # 6. FAILED
        self.job_store.mark_failed(job_id, error_code="INVALID_ARCHIVE", error_message="Corrupted zip header")
        self.assertEqual(self.job_store.get_job(job_id)["status"], STATUS_FAILED)

        # 7. COMPLETED
        self.job_store.mark_completed(job_id, provider="ComicVine", provider_id="4000-12345", confidence=95.0)
        completed = self.job_store.get_job(job_id)
        self.assertEqual(completed["status"], STATUS_COMPLETED)
        self.assertEqual(completed["provider"], "ComicVine")
        self.assertEqual(completed["confidence"], 95.0)

    # ------------------------------------------------------------------ #
    # 85.2: Hash Tracker as Idempotency Data                             #
    # ------------------------------------------------------------------ #
    def test_85_2_hash_tracker_as_idempotency_data(self):
        """85.2: Tracker determines if exact archive state was already processed without managing job state."""
        cbz = self._create_sample_cbz("Batman #002 (2016).cbz")
        
        # Initial check: Not processed yet
        self.assertFalse(is_file_unchanged(cbz, self.cache_mgr))

        # Mark processed
        mark_file_processed(cbz, self.cache_mgr, provider_used="ComicVine")
        self.assertTrue(is_file_unchanged(cbz, self.cache_mgr))

        # Modify file content (breaks idempotency)
        time.sleep(0.01)
        with open(cbz, "ab") as f:
            f.write(b"appended_data")
        os.utime(cbz, None)

        self.assertFalse(is_file_unchanged(cbz, self.cache_mgr))

    # ------------------------------------------------------------------ #
    # 85.3: ProcessingQueue Execution Lifecycle                          #
    # ------------------------------------------------------------------ #
    def test_85_3_processing_queue_execution_lifecycle(self):
        """85.3: ProcessingQueue executes claim -> execute -> report -> complete lifecycle against JobStore."""
        cbz = self._create_sample_cbz("Batman #003 (2016).cbz")
        
        queue = ProcessingQueue(self.cfg, cache_mgr=self.cache_mgr, job_store=self.job_store)
        
        # Mock resolver metadata return
        mock_comic = Comic(series="Batman", number="3", year=2016, publisher="DC Comics")
        queue.resolver.resolve_file_metadata = MagicMock(return_value=(mock_comic, "ComicVine"))

        item = queue.enqueue_file(cbz)
        self.assertIsNotNone(item.job_id)
        
        # Verify job was QUEUED in JobStore upon enqueue
        queued_job = self.job_store.get_job(item.job_id)
        self.assertIn(queued_job["status"], (STATUS_QUEUED, "PENDING"))

        # Run worker loop
        queue.start(workers=1)
        queue.wait_completion()
        queue.stop()

        # Verify job is COMPLETED in JobStore
        final_job = self.job_store.get_job(item.job_id)
        self.assertEqual(final_job["status"], STATUS_COMPLETED)
        self.assertEqual(final_job["provider"], "ComicVine")
        self.assertTrue(len(final_job["sha256"]) > 0)
        self.assertEqual(item.status, "completed")

        # Verify idempotency data recorded
        self.assertTrue(is_file_unchanged(cbz, self.cache_mgr))


if __name__ == "__main__":
    unittest.main()
