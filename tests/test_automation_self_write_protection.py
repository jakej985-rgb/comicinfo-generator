"""
Phase 51 — Automation Self-Write Protection Tests (Sections 51.1 - 51.2)

Tests:
1. Self-write modification loop prevention (processing count == 1)
2. Watchdog modification event ignored when caused by own write (SHA256 fingerprinting)
3. Watcher restart verification (no immediate reprocessing of unchanged/known files)
4. Detection and processing of actual external file modifications
"""
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch, MagicMock

from watchdog.events import FileCreatedEvent, FileModifiedEvent

from config import Config
from models.comic import Comic
from cache.db import CacheManager
from cache.tracker import is_file_unchanged, mark_file_processed
from writers.archive import embed_comicinfo_in_cbz
from automation.watcher import ComicFileEventHandler, LibraryWatcher
from automation.queue import ProcessingQueue


class TestAutomationSelfWriteProtection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "watcher_test.db")
        self.cache = CacheManager(db_path=self.db_path)
        self.watch_dir = os.path.join(self.tmp, "library")
        os.makedirs(self.watch_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_sample_cbz(self, name: str = "test.cbz") -> str:
        cbz_path = os.path.join(self.watch_dir, name)
        with zipfile.ZipFile(cbz_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"sample_page_1")
            zf.writestr("002.jpg", b"\xff\xd8\xff\xe0" + b"sample_page_2")
        return cbz_path

    # 51.1: Test modification loop prevention
    def test_self_write_loop_protection(self):
        cbz_path = self._create_sample_cbz("Batman #001 (2016).cbz")
        processed_count = 0

        def on_file_changed(fpath: str):
            nonlocal processed_count
            processed_count += 1
            # Simulate pipeline processing: embed ComicInfo.xml and record fingerprint
            comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")
            embed_comicinfo_in_cbz(fpath, comic)
            mark_file_processed(fpath, self.cache, provider_used="ComicVine")

        handler = ComicFileEventHandler(
            cache_mgr=self.cache,
            on_file_changed=on_file_changed
        )

        # 1. Watchdog detects new file
        created_event = FileCreatedEvent(cbz_path)
        handler.on_created(created_event)

        self.assertEqual(processed_count, 1)

        # 2. Watchdog fires on_modified event resulting from embed_comicinfo_in_cbz write
        modified_event = FileModifiedEvent(cbz_path)
        handler.on_modified(modified_event)

        # 3. Must still be exactly 1 — NOT a recursive processing loop
        self.assertEqual(processed_count, 1)

        # 4. Repeated filesystem events on the same file must be ignored
        for _ in range(5):
            handler.on_modified(modified_event)

        self.assertEqual(processed_count, 1)

    # 51.2: Restart test
    def test_watcher_restart_does_not_reprocess(self):
        cbz_path = self._create_sample_cbz("Batman #002 (2016).cbz")
        
        # 1. File was previously processed and recorded in persistent database
        comic = Comic(series="Batman", number="2", year=2016, publisher="DC Comics")
        embed_comicinfo_in_cbz(cbz_path, comic)
        mark_file_processed(cbz_path, self.cache, provider_used="ComicVine")

        # 2. Simulate restarting watcher with the same cache database
        restarted_cache = CacheManager(db_path=self.db_path)
        restarted_processed_count = 0

        def on_restarted_file_changed(fpath: str):
            nonlocal restarted_processed_count
            restarted_processed_count += 1

        restarted_handler = ComicFileEventHandler(
            cache_mgr=restarted_cache,
            on_file_changed=on_restarted_file_changed
        )

        # 3. Simulate startup file scan / modification events
        restarted_handler.on_modified(FileModifiedEvent(cbz_path))
        restarted_handler.on_created(FileCreatedEvent(cbz_path))

        # 4. Must NOT reprocess previously processed file
        self.assertEqual(restarted_processed_count, 0)
        self.assertTrue(is_file_unchanged(cbz_path, restarted_cache))

    # Test external file change detection
    def test_external_file_modification_is_processed(self):
        cbz_path = self._create_sample_cbz("Batman #003 (2016).cbz")
        processed_count = 0

        def on_file_changed(fpath: str):
            nonlocal processed_count
            processed_count += 1
            mark_file_processed(fpath, self.cache, provider_used="ComicVine")

        handler = ComicFileEventHandler(
            cache_mgr=self.cache,
            on_file_changed=on_file_changed
        )

        # Initial processing
        handler.on_created(FileCreatedEvent(cbz_path))
        self.assertEqual(processed_count, 1)

        # External modification: add a page to the CBZ
        time.sleep(0.01) # ensure mtime change
        with zipfile.ZipFile(cbz_path, "a") as zf:
            zf.writestr("003.jpg", b"\xff\xd8\xff\xe0" + b"sample_page_3")

        # Watchdog fires for external user modification
        handler.on_modified(FileModifiedEvent(cbz_path))

        # Must be processed again (count = 2)
        self.assertEqual(processed_count, 2)


if __name__ == "__main__":
    unittest.main()
