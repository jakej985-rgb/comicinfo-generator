"""
tests/test_watcher_reliability.py — Phase 86: Watcher Reliability Tests

Verifies:
1. 86.1: File Stability Detection (waits until file size and mtime settle before processing).
2. 86.2: Event Debouncing (collapses rapid burst of create/modify events into a single job).
3. 86.3: Rename and Move Events (on_moved correctly tracks old -> new path, cancels stale timers).
4. 86.4: Full Watcher Restart Lifecycle (application stops -> restarts -> 0 duplicate processing).
"""

import os
import shutil
import tempfile
import time
import unittest
import zipfile
from unittest.mock import MagicMock
from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileMovedEvent, FileDeletedEvent

from config import Config
from cache.db import CacheManager
from cache.tracker import is_file_unchanged, mark_file_processed
from writers.archive import embed_comicinfo_in_cbz
from models.comic import Comic
from automation.watcher import ComicFileEventHandler, LibraryWatcher, wait_until_file_stable


class TestWatcherReliability(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase86_watch_")
        self.db_path = os.path.join(self.tmp, "cache.db")
        self.cache_mgr = CacheManager(self.db_path)
        self.watch_dir = os.path.join(self.tmp, "library")
        os.makedirs(self.watch_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_sample_cbz(self, name: str) -> str:
        path = os.path.join(self.watch_dir, name)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"sample_comic_data")
        return path

    # ------------------------------------------------------------------ #
    # 86.1: File Stability Detection                                     #
    # ------------------------------------------------------------------ #
    def test_86_1_wait_until_file_stable(self):
        """86.1: wait_until_file_stable detects when active file writes conclude."""
        cbz = self._create_sample_cbz("SpiderMan_001.cbz")
        
        # Immediate check with small stability window
        self.assertTrue(wait_until_file_stable(cbz, stability_window=0.05, check_interval=0.02, max_wait=1.0))

        # Missing file returns False
        missing_path = os.path.join(self.watch_dir, "nonexistent.cbz")
        self.assertFalse(wait_until_file_stable(missing_path, stability_window=0.05, max_wait=0.2))

    # ------------------------------------------------------------------ #
    # 86.2: Debounce Rapid Events                                        #
    # ------------------------------------------------------------------ #
    def test_86_2_debounce_rapid_events_collapses_to_single_job(self):
        """86.2: Multiple rapid create/modify events for one file trigger exactly 1 callback invocation."""
        cbz = self._create_sample_cbz("Batman #001 (2016).cbz")
        processed_files = []

        def on_file_changed(fpath: str):
            processed_files.append(fpath)

        handler = ComicFileEventHandler(
            cache_mgr=self.cache_mgr,
            on_file_changed=on_file_changed,
            debounce_delay=0.15,
            stability_window=0.0
        )

        # Fire rapid sequence of events (simulate active downloading / unzipping)
        handler.on_created(FileCreatedEvent(cbz))
        handler.on_modified(FileModifiedEvent(cbz))
        handler.on_modified(FileModifiedEvent(cbz))
        handler.on_modified(FileModifiedEvent(cbz))

        # Should NOT have fired yet during debounce window
        self.assertEqual(len(processed_files), 0)

        # Wait for debounce timer to fire
        time.sleep(0.3)

        # Must have fired exactly once
        self.assertEqual(len(processed_files), 1)
        self.assertEqual(processed_files[0], os.path.abspath(cbz))
        handler.cancel_all_timers()

    # ------------------------------------------------------------------ #
    # 86.3: Rename, Move, and Delete Events                              #
    # ------------------------------------------------------------------ #
    def test_86_3_handle_move_and_rename_events(self):
        """86.3: on_moved cancels stale source timer and schedules destination."""
        old_cbz = self._create_sample_cbz("OldName #001.cbz")
        new_cbz = os.path.join(self.watch_dir, "NewName #001.cbz")
        os.rename(old_cbz, new_cbz)

        processed_files = []
        handler = ComicFileEventHandler(
            cache_mgr=self.cache_mgr,
            on_file_changed=lambda p: processed_files.append(p),
            debounce_delay=0.1,
            stability_window=0.0
        )

        # Fire on_created for old path, then immediately on_moved to new path
        handler.on_created(FileCreatedEvent(old_cbz))
        handler.on_moved(FileMovedEvent(old_cbz, new_cbz))

        time.sleep(0.25)

        # Only the new destination path must be processed
        self.assertEqual(processed_files, [os.path.abspath(new_cbz)])
        handler.cancel_all_timers()

    def test_86_3_handle_delete_event(self):
        """86.3: on_deleted cancels any pending timer without errors."""
        cbz = self._create_sample_cbz("DeleteMe #001.cbz")
        processed_files = []
        handler = ComicFileEventHandler(
            cache_mgr=self.cache_mgr,
            on_file_changed=lambda p: processed_files.append(p),
            debounce_delay=0.15,
            stability_window=0.0
        )

        handler.on_created(FileCreatedEvent(cbz))
        handler.on_deleted(FileDeletedEvent(cbz))

        time.sleep(0.25)
        self.assertEqual(len(processed_files), 0)
        handler.cancel_all_timers()

    # ------------------------------------------------------------------ #
    # 86.4: Full Watcher Restart Lifecycle Test                          #
    # ------------------------------------------------------------------ #
    def test_86_4_watcher_restart_zero_duplicate_processing(self):
        """86.4: Application stop -> restart with unchanged library -> ZERO duplicate processing."""
        cbz = self._create_sample_cbz("Superman #001 (2018).cbz")

        # 1. First run: process file and record fingerprint in hash tracker
        comic = Comic(series="Superman", number="1", year=2018, publisher="DC Comics")
        embed_comicinfo_in_cbz(cbz, comic)
        mark_file_processed(cbz, self.cache_mgr, provider_used="ComicVine")

        self.assertTrue(is_file_unchanged(cbz, self.cache_mgr))

        # 2. Simulate full application shutdown and restart
        restarted_cache = CacheManager(self.db_path)
        restarted_processed = []

        watcher = LibraryWatcher(
            watch_path=self.watch_dir,
            cache_mgr=restarted_cache,
            on_file_changed=lambda p: restarted_processed.append(p),
            debounce_delay=0.05,
            stability_window=0.0
        )
        watcher.start()

        # Simulate watchdog scanner / filesystem events arriving after restart
        watcher.handler.on_created(FileCreatedEvent(cbz))
        watcher.handler.on_modified(FileModifiedEvent(cbz))

        time.sleep(0.2)
        watcher.stop()

        # 3. ZERO duplicate processing
        self.assertEqual(len(restarted_processed), 0)


if __name__ == "__main__":
    unittest.main()
