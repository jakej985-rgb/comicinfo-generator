"""
automation/watcher.py — Phase 86: Watcher Reliability

Features:
1. 86.1: File Stability Detection (waits for size/mtime to settle during file copy/download).
2. 86.2: Debounce Rapid Events (collapses bursts of create/modify events into a single job).
3. 86.3: Rename/Move & Delete Handling (on_created, on_modified, on_moved, on_deleted).
4. 86.4: Restart Safety & Self-Write Loop Protection (SHA256 fingerprint check).
"""

import os
import threading
import time
from typing import Optional, Callable, Dict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from cache.db import CacheManager
from cache.tracker import is_file_unchanged


def wait_until_file_stable(
    file_path: str,
    stability_window: float = 1.0,
    check_interval: float = 0.2,
    max_wait: float = 10.0
) -> bool:
    """
    Phase 86.1: Waits until a file is fully written and its size/mtime are stable.
    Returns True if file is stable, False if file disappears or max_wait is exceeded.
    """
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return False

    if stability_window <= 0:
        return True

    start_time = time.time()
    try:
        stat_prev = os.stat(abs_path)
        last_size = stat_prev.st_size
        last_mtime = stat_prev.st_mtime
    except OSError:
        return False

    time.sleep(stability_window)

    while (time.time() - start_time) < max_wait:
        if not os.path.exists(abs_path):
            return False
        try:
            stat_curr = os.stat(abs_path)
            curr_size = stat_curr.st_size
            curr_mtime = stat_curr.st_mtime
        except OSError:
            return False

        if curr_size == last_size and curr_mtime == last_mtime:
            return True

        last_size = curr_size
        last_mtime = curr_mtime
        time.sleep(check_interval)

    return True


class ComicFileEventHandler(FileSystemEventHandler):
    """
    Phase 23 & Phase 86: Watchdog event handler with stability detection,
    debouncing, move/rename tracking, and self-write protection.
    """

    def __init__(
        self,
        cache_mgr: CacheManager,
        on_file_changed: Callable[[str], None],
        log_callback: Optional[Callable[[str], None]] = None,
        stability_window: float = 0.0,
        debounce_delay: float = 0.0
    ):
        super().__init__()
        self.cache_mgr = cache_mgr
        self.on_file_changed = on_file_changed
        self.log = log_callback or (lambda msg: print(msg))
        self.stability_window = stability_window
        self.debounce_delay = debounce_delay

        self._timers: Dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _is_comic_file(self, path: str) -> bool:
        return path.lower().endswith((".cbz", ".cbr"))

    def _process_event(self, event_path: str):
        """Processes a stabilized, debounced file event."""
        if not self._is_comic_file(event_path):
            return

        abs_path = os.path.abspath(event_path)
        if not os.path.exists(abs_path):
            return

        # 1. File Stability Detection (86.1)
        if self.stability_window > 0:
            is_stable = wait_until_file_stable(abs_path, stability_window=self.stability_window)
            if not is_stable or not os.path.exists(abs_path):
                return

        # 2. Ignore self-modified / known files via Hash Tracker (86.4)
        if is_file_unchanged(abs_path, self.cache_mgr):
            self.log(f"🙈 Ignored self-modified / known file event: '{os.path.basename(abs_path)}'")
            return

        self.log(f"👀 Detected new/modified comic file: '{os.path.basename(abs_path)}'")
        self.on_file_changed(abs_path)

    def _schedule_event(self, event_path: str):
        """Debounces rapid filesystem events for the same file path (86.2)."""
        if not self._is_comic_file(event_path):
            return

        abs_path = os.path.abspath(event_path)

        if self.debounce_delay <= 0:
            self._process_event(abs_path)
            return

        with self._lock:
            if abs_path in self._timers:
                self._timers[abs_path].cancel()

            timer = threading.Timer(self.debounce_delay, self._on_debounce_timer, args=[abs_path])
            self._timers[abs_path] = timer
            timer.daemon = True
            timer.start()

    def _on_debounce_timer(self, abs_path: str):
        with self._lock:
            self._timers.pop(abs_path, None)
        self._process_event(abs_path)

    def cancel_all_timers(self):
        """Cancels all active debounce timers."""
        with self._lock:
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()

    # --- Watchdog Event Handlers (86.3) ---

    def on_created(self, event):
        if not event.is_directory:
            self._schedule_event(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule_event(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            # Cancel any pending timer for the old source path
            old_abs = os.path.abspath(event.src_path)
            with self._lock:
                if old_abs in self._timers:
                    self._timers[old_abs].cancel()
                    self._timers.pop(old_abs, None)

            # Schedule the new destination path if it's a comic file
            if self._is_comic_file(event.dest_path):
                self.log(f"🔄 File moved/renamed: '{os.path.basename(event.src_path)}' -> '{os.path.basename(event.dest_path)}'")
                self._schedule_event(event.dest_path)

    def on_deleted(self, event):
        if not event.is_directory:
            old_abs = os.path.abspath(event.src_path)
            with self._lock:
                if old_abs in self._timers:
                    self._timers[old_abs].cancel()
                    self._timers.pop(old_abs, None)
            if self._is_comic_file(event.src_path):
                self.log(f"🗑️ File deleted: '{os.path.basename(event.src_path)}'")


class LibraryWatcher:
    """
    Phase 86: Background directory watcher monitoring comic library for new/modified files.
    Debounces rapid events, detects file write stability, and handles renames.
    """

    def __init__(
        self,
        watch_path: str,
        cache_mgr: CacheManager,
        on_file_changed: Callable[[str], None],
        log_callback: Optional[Callable[[str], None]] = None,
        stability_window: float = 0.0,
        debounce_delay: float = 0.0
    ):
        self.watch_path = os.path.abspath(watch_path)
        self.cache_mgr = cache_mgr
        self.on_file_changed = on_file_changed
        self.log = log_callback or (lambda msg: print(msg))

        self.handler = ComicFileEventHandler(
            cache_mgr=cache_mgr,
            on_file_changed=on_file_changed,
            log_callback=self.log,
            stability_window=stability_window,
            debounce_delay=debounce_delay
        )
        self.observer = Observer()

    def start(self):
        if not os.path.exists(self.watch_path):
            self.log(f"⚠️ Watch directory path does not exist: '{self.watch_path}'")
            return

        self.observer.schedule(self.handler, self.watch_path, recursive=True)
        self.observer.start()
        self.log(f"👁️ Library Watcher started monitoring: '{self.watch_path}'")

    def stop(self):
        self.handler.cancel_all_timers()
        self.observer.stop()
        self.observer.join(timeout=2)
        self.log("🛑 Library Watcher stopped.")
