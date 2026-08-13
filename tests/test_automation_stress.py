"""
Phase 63 — Automation Stress Tests

Verifies:
1. 63.1 Self-write test: Watcher ignores automation's own writes (single cycle processing).
2. 63.2 Restart test: Processed state persists in DB; restart skips unchanged archives.
3. 63.3 Rapid modification test: Rapid bursts of events on same file deduplicate safely.
4. 63.4 Failed processing test: Provider/archive failures transition to FAILED without retry loops.
"""
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

from config import Config, load_config
from cache.db import CacheManager
from cache.tracker import is_file_unchanged, mark_file_processed
from automation.watcher import ComicFileEventHandler
from automation.queue import ProcessingQueue
from models.comic import Comic


class MockFileSystemEvent:
    def __init__(self, src_path: str, is_directory: bool = False):
        self.src_path = src_path
        self.is_directory = is_directory


class TestAutomationStress(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "cache.db")
        self.cache_mgr = CacheManager(self.db_path)
        self.comics_dir = os.path.join(self.tmp, "comics")
        os.makedirs(self.comics_dir, exist_ok=True)

        self.cbz_path = os.path.join(self.comics_dir, "Batman #001 (2016).cbz")
        with zipfile.ZipFile(self.cbz_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"page_data_1")

        self.config = load_config()
        self.config.cache.db_path = self.db_path
        self.config.cache.enabled = True

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_self_write_single_cycle(self):
        """63.1: Watcher detects new file once, processes it, and subsequent write is ignored."""
        processed_callbacks = []

        def on_changed(fpath):
            processed_callbacks.append(fpath)
            # Simulate embedding by marking file processed in DB
            mark_file_processed(fpath, self.cache_mgr, provider_used="ComicVine")

        handler = ComicFileEventHandler(self.cache_mgr, on_changed)

        # 1. First event: file created
        handler.on_created(MockFileSystemEvent(self.cbz_path))
        self.assertEqual(len(processed_callbacks), 1)

        # 2. Second event: filesystem fires modified event from embedding write
        handler.on_modified(MockFileSystemEvent(self.cbz_path))

        # Assert exactly 1 processing cycle occurred (self-write ignored)
        self.assertEqual(len(processed_callbacks), 1)

    def test_restart_persists_skip_state(self):
        """63.2: Process file, restart application/watcher, verify unchanged archive is skipped."""
        # 1. Process and mark file
        mark_file_processed(self.cbz_path, self.cache_mgr, provider_used="ComicVine")

        # 2. Simulate application restart with new CacheManager and new handler/queue
        restarted_cache = CacheManager(self.db_path)
        triggered = []

        restarted_handler = ComicFileEventHandler(restarted_cache, lambda p: triggered.append(p))

        # 3. Simulate startup / watcher scan event
        restarted_handler.on_modified(MockFileSystemEvent(self.cbz_path))

        # Assert no re-processing triggered
        self.assertEqual(len(triggered), 0)
        self.assertTrue(is_file_unchanged(self.cbz_path, restarted_cache))

    def test_rapid_modification_deduplication(self):
        """63.3: Rapid multiple event bursts on same file deduplicate into a single active job."""
        queue_mgr = ProcessingQueue(self.config, self.cache_mgr)

        # Enqueue same file 5 times rapidly
        items = [queue_mgr.enqueue_file(self.cbz_path) for _ in range(5)]

        # All returned items should reference the same deduplicated item instance
        self.assertEqual(len(queue_mgr.results), 1)
        self.assertIs(items[0], items[1])
        self.assertIs(items[1], items[4])
        self.assertEqual(queue_mgr.work_queue.qsize(), 1)

    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    def test_failed_processing_no_infinite_loop(self, MockKap, MockCV):
        """63.4: Forced provider/metadata failure transitions to FAILED status without loop."""
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []

        queue_mgr = ProcessingQueue(self.config, self.cache_mgr)
        item = queue_mgr.enqueue_file(self.cbz_path)

        queue_mgr.start(workers=1)
        queue_mgr.wait_completion()
        queue_mgr.stop()

        self.assertEqual(item.status, "failed")
        self.assertEqual(queue_mgr.work_queue.qsize(), 0)
        self.assertEqual(len(queue_mgr.results), 1)


if __name__ == "__main__":
    unittest.main()
