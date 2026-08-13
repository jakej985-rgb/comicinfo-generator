import os
import time
from typing import Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from cache.db import CacheManager
from cache.tracker import is_file_unchanged

class ComicFileEventHandler(FileSystemEventHandler):
    """
    Phase 23: Watchdog event handler that ignores self-modified files.
    Checks file hash against known processing state before queueing.
    """

    def __init__(
        self,
        cache_mgr: CacheManager,
        on_file_changed: Callable[[str], None],
        log_callback: Optional[Callable[[str], None]] = None
    ):
        super().__init__()
        self.cache_mgr = cache_mgr
        self.on_file_changed = on_file_changed
        self.log = log_callback or (lambda msg: print(msg))

    def _process_event(self, event_path: str):
        if not event_path.lower().endswith((".cbz", ".cbr")):
            return

        abs_path = os.path.abspath(event_path)
        if not os.path.exists(abs_path):
            return

        # Phase 23: Ignore automation's own changes by verifying hash against known state
        if is_file_unchanged(abs_path, self.cache_mgr):
            self.log(f"🙈 Ignored self-modified / known file event: '{os.path.basename(abs_path)}'")
            return

        self.log(f"👀 Detected new/modified comic file: '{os.path.basename(abs_path)}'")
        self.on_file_changed(abs_path)

    def on_created(self, event):
        if not event.is_directory:
            self._process_event(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._process_event(event.src_path)


class LibraryWatcher:
    """
    Background directory watcher monitoring comic library for new/modified files.
    Safe against processing loops.
    """

    def __init__(
        self,
        watch_path: str,
        cache_mgr: CacheManager,
        on_file_changed: Callable[[str], None],
        log_callback: Optional[Callable[[str], None]] = None
    ):
        self.watch_path = os.path.abspath(watch_path)
        self.cache_mgr = cache_mgr
        self.on_file_changed = on_file_changed
        self.log = log_callback or (lambda msg: print(msg))

        self.handler = ComicFileEventHandler(cache_mgr, on_file_changed, log_callback=self.log)
        self.observer = Observer()

    def start(self):
        if not os.path.exists(self.watch_path):
            self.log(f"⚠️ Watch directory path does not exist: '{self.watch_path}'")
            return

        self.observer.schedule(self.handler, self.watch_path, recursive=True)
        self.observer.start()
        self.log(f"👁️ Library Watcher started monitoring: '{self.watch_path}'")

    def stop(self):
        self.observer.stop()
        self.observer.join(timeout=2)
        self.log("🛑 Library Watcher stopped.")
