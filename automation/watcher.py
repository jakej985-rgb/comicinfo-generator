import os
import time
import threading
from typing import Optional, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from config import Config
from automation.queue import ProcessingQueue

def wait_until_file_stable(file_path: str, timeout: int = 30, check_interval: float = 1.0) -> bool:
    """Waits until file size stops growing (verifies file copy/download has finished)."""
    if not os.path.exists(file_path):
        return False

    start_time = time.time()
    last_size = -1
    stable_count = 0

    while time.time() - start_time < timeout:
        try:
            current_size = os.path.getsize(file_path)
            if current_size == last_size and current_size > 0:
                stable_count += 1
                if stable_count >= 2:
                    return True
            else:
                stable_count = 0
                last_size = current_size
        except Exception:
            pass
        time.sleep(check_interval)

    return os.path.exists(file_path)

class ComicFileEventHandler(FileSystemEventHandler):
    def __init__(self, queue_mgr: ProcessingQueue, log_callback: Optional[Callable[[str], None]] = None):
        self.queue_mgr = queue_mgr
        self.log = log_callback or (lambda msg: print(msg))

    def _process_event(self, event_path: str):
        if event_path.lower().endswith((".cbz", ".cbr")):
            self.log(f"🔔 File change detected: '{os.path.basename(event_path)}'")
            # Run in separate thread to avoid blocking watchdog observer loop
            def delayed_enqueue():
                if wait_until_file_stable(event_path):
                    self.queue_mgr.enqueue_file(event_path)
            threading.Thread(target=delayed_enqueue, daemon=True).start()

    def on_created(self, event):
        if not event.is_directory:
            self._process_event(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._process_event(event.src_path)

class LibraryWatcher:
    """
    Filesystem Watcher for continuous library automation.
    Monitors target library folder for newly added or updated .cbz / .cbr files.
    """

    def __init__(self, config: Config, queue_mgr: Optional[ProcessingQueue] = None):
        self.config = config
        self.queue_mgr = queue_mgr or ProcessingQueue(config)
        self.observer = None

    def start_watching(self, folder_path: Optional[str] = None):
        watch_dir = os.path.expanduser(folder_path or self.config.automation.watch_folder or os.getcwd())
        if not os.path.exists(watch_dir):
            os.makedirs(watch_dir, exist_ok=True)

        self.queue_mgr.start()

        event_handler = ComicFileEventHandler(self.queue_mgr)
        self.observer = Observer()
        self.observer.schedule(event_handler, path=watch_dir, recursive=True)
        self.observer.start()

        print(f"==================================================")
        print(f" 👁️  Library Watcher Active: '{watch_dir}'")
        print(f" Workers: {self.config.automation.workers} | Press Ctrl+C to stop.")
        print(f"==================================================")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
        self.queue_mgr.stop()
        print("🛑 Library Watcher stopped.")
