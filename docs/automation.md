# Automation — ComicInfo Generator

## Purpose

Describes the automation pipeline: library watching, job queuing,
durable state, and restart safety.

---

## Responsibilities

| Module | Responsibility |
|---|---|
| `automation/watcher.py` | Watches library directories for new/modified archives |
| `automation/queue.py` | Thread pool execution of processing jobs |
| `cache/jobs.py` | Durable SQLite job queue — survives crashes and restarts |

---

## Inputs

- A monitored directory path (configured in `~/.comicinfo/config.yaml`)
- `automation.mode`: `"watch"` | `"batch"` | `"manual"`
- `automation.workers`: number of concurrent worker threads

---

## Outputs

- `ComicInfo.xml` embedded into each matched archive
- Job state recorded in `cache/jobs.py` (`PENDING` → `PROCESSING` → `DONE` / `FAILED`)
- Structured log events via `observability/logging.py`
- Metrics incremented via `observability/metrics.py`

---

## LibraryWatcher Behaviour

`automation/watcher.py → LibraryWatcher`

1. Monitors configured directories via inotify (Linux) or polling fallback
2. On file creation or modification:
   a. Reads SHA256 of the file
   b. Checks `cache/db.py → file_hashes` table for existing `sha256`
   c. If SHA256 already present with `status=SUCCESS` → skips (self-write guard)
   d. If new or modified → enqueues a `PENDING` job in `cache/jobs.py`

### Self-Write Guard

The watcher **ignores its own file modifications** by:
- Checking `file_hashes` for the current `sha256` before queuing
- Never re-queuing a file that the pipeline itself just wrote

This prevents infinite re-processing loops when `embed_comicinfo_in_cbz` modifies an archive.

---

## Durable Job Queue (`cache/jobs.py`)

Jobs survive application crashes:

```text
PENDING → PROCESSING → DONE
                  ↓
               FAILED
```

On startup, any jobs stuck in `PROCESSING` are reset to `PENDING` (restart-safe recovery).

Primary key: `(file_path, sha256)` — prevents duplicate jobs for the same file version.

---

## Deduplication

A job is only enqueued if no `PENDING` or `PROCESSING` job already exists for  
the same `(file_path, sha256)` pair.

---

## Dry-Run Mode

When `main.py --dry-run` is passed:
- Jobs are simulated: identity is resolved and scored
- **No archive is modified**
- **No file hash is written**
- **No job state is written**
- Output is printed to stdout in table format

---

## Rate Limiting

Concurrent workers share the same `rate_limiter` singleton from `observability/rate_limiter.py`.  
Workers run concurrently, but HTTP calls to external providers are serialised through per-provider token buckets.

---

## Invariants

1. A file is never reprocessed if its SHA256 already exists in `file_hashes` with `SUCCESS`.
2. `PROCESSING` jobs are always reset to `PENDING` on startup to prevent stuck queues.
3. Dry-run mode never modifies any file or database record.
4. Worker failures are recorded in `cache/jobs.py` with `status=FAILED` and `error_message`.

---

## Failure Modes

| Failure | Result |
|---|---|
| Archive write error | Job recorded as `FAILED`, original archive safe |
| Provider all offline | Job recorded as `UNRESOLVED`, can be retried |
| Watcher crash | Jobs already in `PENDING` will be picked up on next startup |
| Worker thread crash | Job stuck in `PROCESSING` → reset to `PENDING` on next startup |

---

## Testing Requirements

- The self-write guard must be tested: a file written by the pipeline must not trigger re-queuing.
- Restart recovery must be tested: jobs in `PROCESSING` on startup must be reset to `PENDING`.
- Dry-run mode must be tested: asserts zero archive modifications occur.

---

## Do-Not-Do Rules

- Do not modify archives outside of `services/processing.py → embed_and_track`.
- Do not skip SHA256 checking before queuing.
- Do not leave jobs in `PROCESSING` permanently — always recover on startup.
- Do not run workers without rate limiting for external providers.
