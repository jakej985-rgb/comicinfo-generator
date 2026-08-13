# Actual Automation — ComicInfo Generator

## 1. Overview

Automation in `comicinfo-generator` covers background task queuing, batch processing endpoints, and library scanning.

---

## 2. In-Memory Task Queue (`automation/queue.py`)

`automation/queue.py` implements a simple thread-safe worker queue using Python's `queue.Queue` and `concurrent.futures.ThreadPoolExecutor`:

- `TaskQueue(num_workers=2)`: Launches worker threads that pull items from an in-memory FIFO queue.
- `add_task(task_id, func, *args)`: Adds async callable tasks to queue.
- `get_status(task_id)`: Returns task progress state (`pending`, `processing`, `success`, `error`).

---

## 3. Web UI Batch Streaming Processing (`app.py`)

Batch tagging in the Web UI operates via HTTP streaming endpoints:
- **`POST /api/batch-preview`**: Accepts `folder_path` and `volume_url`. Scrapes the volume page on Comic Vine or GCP, inspects all `.cbz` / `.cbr` files in the folder directory, matches issue numbers using regex and slug filters, and returns a JSON list of matches.
- **`POST /api/batch-embed`**: Accepts a list of match items and streams progress line by line (`chunk.encode('utf-8')` JSON lines) back to the browser:
  - Fetches or retrieves cached issue metadata.
  - Calls `embed_comicinfo_in_cbz(target_archive, comic)`.
  - Calls `mark_file_processed(target_archive, cache_mgr, provider)`.
  - Streams `{"current": N, "total": M, "file": fname, "status": "success"}` updates to update the progress bar in real time.

---

## 4. Automatic Folder Watcher Daemon (Status: Removed)

An earlier file watcher daemon (`automation/watcher.py`) that polled disk directories using `watchdog` was removed in previous refactoring. Unattended watcher capabilities will be rebuilt in accordance with `plan.md` using durable SQLite processing state tracking.
