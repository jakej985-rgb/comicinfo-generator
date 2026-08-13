# Automation — ComicInfo Generator

## Purpose

Describes the automation pipeline: library watching, durable job queuing,
concurrency control, crash recovery, and restart safety.

---

## Responsibilities

| Module | Responsibility |
|---|---|
| `automation/watcher.py` | Watches library directories for new/modified archives with SHA256 loop protection |
| `automation/queue.py` | Thread pool execution of processing jobs with worker lease renewal |
| `cache/jobs.py` | Durable SQLite job queue with `BEGIN IMMEDIATE` exclusive locking and lease recovery |

---

## LibraryWatcher Behaviour

`automation/watcher.py → LibraryWatcher`

1. Monitors configured directories via inotify (Linux) or polling fallback
2. On file creation or modification:
   a. Computes SHA256 of the file using 256KB readinto buffer
   b. Checks `cache/db.py → file_hashes` table for existing `sha256`
   c. If SHA256 already present with `status=SUCCESS` → drops event (self-write guard)
   d. If new or modified → enqueues a `PENDING` job in `cache/jobs.py`

### Self-Write Guard

The watcher **ignores its own file modifications** by:
- Recording `(file_path, sha256)` upon successful embedding via `mark_file_processed`
- Verifying file state via `is_file_unchanged` before enqueuing
- Dropping duplicate inotify events triggered by `os.replace`

---

## Durable Job Queue (`cache/jobs.py`)

Jobs survive crashes and concurrent worker contention:

```text
PENDING ──claim_job (BEGIN IMMEDIATE)──▶ PROCESSING ──success──▶ DONE
   ▲                                         │
   │                                     max_attempts exceeded
   └─── lease expired (crash recovery) ──────┴────────────────▶ FAILED
```

### Concurrency & Lease Invariants

1. **Exclusive Claiming**: `claim_job(worker_id, lease_seconds, max_attempts)` runs inside a `BEGIN IMMEDIATE` transaction to guarantee that no two workers can claim the same job.
2. **Crash & Lease Expiry Recovery**: If a worker crashes or hangs, expired leases (`status = 'PROCESSING' AND lease_until < now AND attempts < max_attempts`) are automatically reclaimed and reset to `PENDING`.
3. **Poison Pill Isolation**: If a job repeatedly fails or crashes workers (`attempts >= max_attempts`), it transitions directly to `FAILED` with `error_code='MAX_ATTEMPTS_EXCEEDED'`.
4. **Active Lease Renewal**: Long-running jobs extend their lease via `renew_lease(job_id, worker_id, extension_seconds)` while actively processing.

---

## Invariants

1. A file is never reprocessed if its SHA256 already exists in `file_hashes` with `SUCCESS`.
2. Concurrent workers never process the same job simultaneously.
3. Stuck or crashed jobs are guaranteed to recover on worker lease expiry.
4. Poison-pill jobs cannot loop indefinitely; they fail after `max_attempts` (default: 3).
5. Dry-run mode never writes to the persistent queue or database.
