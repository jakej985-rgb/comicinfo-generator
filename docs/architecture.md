# Architecture — ComicInfo Generator

## Purpose

Describes the **actual, implemented** architecture of `comicinfo-generator` as of Phase 32+.  
This document reflects real code, not intended design.

---

## Layer Diagram

```text
HTTP/UI  (static/)
   ↓
api/server.py          — HTTPServer bootstrap, no business logic
api/handlers.py        — route dispatch, delegates to service layer
api/serializers.py     — comic_to_dict / dict_to_comic (pure data)
   ↓
services/
  metadata.py          — provider routing, scrape & merge
  search.py            — issue number extraction, provider search
  processing.py        — file discovery, CBR conversion, embed_and_track
   ↓
pipeline/
  resolver.py          — MetadataResolver: identity → metadata
  filename_parser.py   — filename → ParsedFilename identity signals
  scoring.py           — candidate scoring
  confidence.py        — ConfidenceDecision (AUTO_ACCEPT / MANUAL_REVIEW / UNRESOLVED)
  collection.py        — TPB/collected edition pre-merge validation
  merge.py             — field-level metadata merge policy
  issue_order.py       — normalised issue sort (handles 0, 0.5, 1A, Annual)
   ↓
models/
  comic.py             — Comic dataclass
  identity.py          — ComicIdentity + IdentityEvidence dataclasses
   ↓
providers/
  kapowarr.py          — Kapowarr REST API
  comicvine.py         — Comic Vine HTML scraper
  gcp.py               — Grand Comics Database scraper
  story_arc.py         — story arc search + reading-order parser
   ↓
writers/
  archive.py           — atomic CBZ embed (temp → fsync → os.replace → verify)
  comicinfo.py         — ComicInfo.xml generator
   ↓
cache/
  db.py                — CacheManager (SQLite); Phase 30 schema with TTL, schema_version, source_hash
  tracker.py           — mark_file_processed, SHA256 fingerprinting
   ↓
observability/
  logging.py           — structured job event logger (JobEvent key=value)
  metrics.py           — thread-safe counters (MetricsCollector, global `metrics`)
  rate_limiter.py      — per-provider token-bucket rate limiter
  retry.py             — exponential-backoff retry decorator with retryable classification
   ↓
automation/
  watcher.py           — LibraryWatcher (inotify/polling, ignores self-writes)
  queue.py             — ProcessingQueue (ThreadPoolExecutor)
   ↓
cache/jobs.py          — JobStore (SQLite durable queue, restart-safe)
converters/cbr_to_cbz.py — transactional CBR→CBZ conversion
```

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `api/handlers.py` | HTTP routing only — no provider calls, no archive I/O |
| `api/serializers.py` | Comic↔dict conversion only — no business logic |
| `services/metadata.py` | Provider routing, scrape single URLs, merge multi-URL |
| `services/processing.py` | File discovery, CBR conversion, embed_and_track |
| `pipeline/resolver.py` | Two-phase identity resolution: resolve_identity → retrieve_metadata |
| `pipeline/merge.py` | Field-level priority merge (Phase 29): title, publisher, year, summary, creators |
| `pipeline/collection.py` | Pre-merge validation for collected editions (Phase 26) |
| `writers/archive.py` | Atomic archive writes with pre- and post-replacement verification |
| `cache/db.py` | SQLite cache with TTL, schema_version, source_hash per row (Phase 30–31) |
| `observability/` | Structured logging, metrics, rate limiting, retry policy (Phase 33–36) |

---

## Invariants

1. **No live network in unit tests** — all providers are mocked.
2. **No archive modification without verification** — `embed_comicinfo_in_cbz` always runs `verify_cbz_archive` before and after `os.replace`.
3. **No deletion of original CBR until CBZ is fully verified** — enforced in `converters/cbr_to_cbz.py`.
4. **Dry-run mode must not touch any archive** — enforced in `main.py`.
5. **`app.py` is a shim only** — all logic lives in `api/`, `services/`, `pipeline/`.

---

## Failure Modes

| Failure | Handler |
|---|---|
| `ArchiveReadError` | Raised before temp file is created — original is safe |
| `ArchiveWriteError` | Temp file deleted on exception — original is safe |
| `ArchiveValidationError` | Raised if pre- or post-replace verify fails — original is safe |
| Provider timeout | Classified retryable by `observability/retry.py` |
| HTTP 429 / 5xx | Retried with exponential backoff |
| HTTP 404 / 401 | `NonRetryableError` — never retried |
| Stale cache | Invalidated by `schema_version` mismatch or TTL expiry |

---

## Do-Not-Do Rules

- Do not put business logic in `api/handlers.py`.
- Do not call providers directly from `api/`.
- Do not use `int()` on issue numbers — use `pipeline/issue_order.py`.
- Do not merge archives without calling `verify_cbz_archive`.
- Do not add provider-specific fields to `models/comic.py` or `models/identity.py`.
- Do not bypass `MetadataResolver` to fetch metadata directly.
