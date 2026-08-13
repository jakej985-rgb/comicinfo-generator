import os
import time
import queue
import threading
from typing import Optional, List, Callable
from config import Config
from cache.db import CacheManager
from cache.tracker import is_file_unchanged, mark_file_processed
from pipeline.resolver import MetadataResolver
from converters.cbr_to_cbz import convert_cbr_to_cbz
from writers.archive import embed_comicinfo_in_cbz

class ProcessingItem:
    def __init__(self, file_path: str, url_override: str = "", delete_original_cbr: bool = True):
        self.file_path = file_path
        self.url_override = url_override
        self.delete_original_cbr = delete_original_cbr
        self.status = "pending"  # pending, processing, completed, skipped, failed
        self.error_message = ""
        self.target_file = ""
        self.provider_used = ""

class ProcessingQueue:
    """
    Worker Queue Manager for batch and automated library processing.
    Executes parallel worker threads, checks file hash status to skip unchanged files,
    converts CBR to CBZ, resolves metadata, and embeds ComicInfo.xml.
    """

    def __init__(self, config: Config, cache_mgr: Optional[CacheManager] = None, log_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.cache_mgr = cache_mgr or CacheManager(config.cache.db_path)
        self.resolver = MetadataResolver(config, self.cache_mgr)
        self.log_callback = log_callback or (lambda msg: print(msg))

        self.work_queue = queue.Queue()
        self.results = []
        self.lock = threading.Lock()
        self.is_running = False
        self.threads = []

    def log(self, msg: str):
        self.log_callback(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def enqueue_file(self, file_path: str, url_override: str = "") -> ProcessingItem:
        abs_path = os.path.abspath(file_path)
        with self.lock:
            for existing in self.results:
                if existing.file_path == abs_path and existing.status in ("pending", "processing"):
                    return existing
            item = ProcessingItem(file_path=abs_path, url_override=url_override)
            self.results.append(item)
        self.work_queue.put(item)
        return item

    def enqueue_folder(self, folder_path: str, recursive: bool = True) -> List[ProcessingItem]:
        items = []
        folder_abs = os.path.abspath(folder_path)
        if not os.path.exists(folder_abs) or not os.path.isdir(folder_abs):
            return items

        if recursive:
            for root, _, files in os.walk(folder_abs):
                for f in sorted(files):
                    if f.lower().endswith((".cbz", ".cbr")):
                        items.append(self.enqueue_file(os.path.join(root, f)))
        else:
            for f in sorted(os.listdir(folder_abs)):
                if f.lower().endswith((".cbz", ".cbr")):
                    items.append(self.enqueue_file(os.path.join(folder_abs, f)))

        return items

    def _worker_loop(self):
        while self.is_running:
            try:
                item = self.work_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                item.status = "processing"
                file_path = item.file_path

                # 1. Skip check if file unchanged
                if self.config.cache.enabled and is_file_unchanged(file_path, self.cache_mgr) and not self.config.output.overwrite:
                    item.status = "skipped"
                    item.target_file = file_path
                    self.log(f"⚡ Skipped unchanged file: '{os.path.basename(file_path)}'")
                    continue

                # 2. Handle CBR conversion if needed
                target_archive = file_path
                if file_path.lower().endswith(".cbr"):
                    self.log(f"📦 Converting CBR to CBZ: '{os.path.basename(file_path)}'...")
                    target_archive = convert_cbr_to_cbz(file_path, delete_original=self.config.output.delete_cbr)

                item.target_file = target_archive

                # 3. Resolve Metadata
                self.log(f"🔍 Resolving metadata for: '{os.path.basename(target_archive)}'...")
                comic, provider_used = self.resolver.resolve_file_metadata(target_archive, url_override=item.url_override)
                item.provider_used = provider_used

                if not comic:
                    item.status = "failed"
                    item.error_message = "No metadata found"
                    self.log(f"⚠️ Failed to resolve metadata for '{os.path.basename(target_archive)}'")
                    continue

                # 4. Embed ComicInfo.xml into archive
                self.log(f"⚡ Embedding ComicInfo.xml [{provider_used}] into '{os.path.basename(target_archive)}'...")
                embed_comicinfo_in_cbz(target_archive, comic)

                # 5. Mark file processed in hash tracker
                mark_file_processed(target_archive, self.cache_mgr, provider_used=provider_used)

                item.status = "completed"
                self.log(f"✅ Successfully tagged '{os.path.basename(target_archive)}' [{provider_used}]")

            except Exception as e:
                item.status = "failed"
                item.error_message = str(e)
                self.log(f"❌ Error processing '{os.path.basename(item.file_path)}': {e}")
            finally:
                self.work_queue.task_done()

    def start(self, workers: Optional[int] = None):
        num_workers = workers or self.config.automation.workers
        self.is_running = True
        self.threads = []
        for i in range(num_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True, name=f"Worker-{i+1}")
            t.start()
            self.threads.append(t)
        self.log(f"🚀 Processing Queue started with {num_workers} parallel workers.")

    def wait_completion(self):
        self.work_queue.join()

    def stop(self):
        self.is_running = False
        for t in self.threads:
            t.join(timeout=2)
        self.log("🛑 Processing Queue stopped.")
