# Architecture — ComicInfo Generator

## Purpose

Describes the **actual, implemented** architecture of `comicinfo-generator` as of Phase 53.  
This document reflects real code and enforced boundaries.

---

## Layer Diagram

```text
HTTP/UI  (static/)
   ↓
api/server.py          — HTTPServer bootstrap, no business logic
api/handlers.py        — route dispatch, delegates strictly to services/
api/serializers.py     — comic_to_dict / dict_to_comic (pure data transformation)
   ↓
services/
  metadata.py          — provider routing, scrape & merge
  search.py            — issue number extraction, provider search
  processing.py        — file discovery, CBR conversion, embed_and_track
  kapowarr.py          — Kapowarr library, connection, and issue download service
  story_arc.py         — Story arc search, issue retrieval, and library fix service
   ↓
pipeline/
  resolver.py          — MetadataResolver: two-phase identity → metadata
  filename_parser.py   — filename → ParsedFilename identity signals
  scoring.py           — candidate scoring with configurable weights
  confidence.py        — Central Decision Policy (AUTO_ACCEPT / MANUAL_REVIEW / UNRESOLVED)
  conflicts.py         — provider disagreement & existing XML conflict detection
  existing_metadata.py — existing embedded ComicInfo.xml state inspection & classification
  collection.py        — TPB/collected edition pre-merge validation
  merge.py             — field-level metadata merge policy with provenance tracking
  issue_order.py       — normalized issue sorting (0, 0.5, 1A, Annual, Special)
  dry_run.py           — DryRunContext: in-memory SQLite & archive write interceptor
   ↓
models/
  comic.py             — Comic dataclass
  identity.py          — ComicIdentity + IdentityEvidence dataclasses
   ↓
providers/
  kapowarr.py          — Kapowarr REST API (with library snapshot caching)
  comicvine.py         — Comic Vine HTML scraper
  gcp.py               — Grand Comics Database scraper
  story_arc.py         — story arc search + reading-order parser
   ↓
writers/
  archive.py           — 9-step atomic CBZ embed (CRC verify → fsync → fsync dir → os.replace → CRC verify)
  comicinfo.py         — ComicInfo.xml generator with unknown tag preservation
   ↓
cache/
  db.py                — CacheManager (SQLite WAL, TTL, schema_version, source_hash, :memory: support)
  jobs.py              — JobStore (Durable queue, BEGIN IMMEDIATE leases, max_attempts recovery)
  tracker.py           — mark_file_processed, calculate_sha256 with 256KB readinto buffer
   ↓
observability/
  logging.py           — structured job event logger (JobEvent key=value format)
  metrics.py           — thread-safe metrics counters and histograms (MetricsCollector)
  rate_limiter.py      — per-provider token-bucket rate limiter
  retry.py             — exponential-backoff retry decorator with typed error classification
   ↓
automation/
  watcher.py           — LibraryWatcher (inotify/polling, SHA256 self-write filter)
  queue.py             — ProcessingQueue (ThreadPoolExecutor with durable worker leases)
converters/cbr_to_cbz.py — transactional CBR→CBZ conversion
```

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `api/handlers.py` | HTTP routing only — delegates strictly to `services/`, `pipeline.resolver`, or `cache/` (0 provider imports) |
| `api/serializers.py` | Comic↔dict conversion only — no business logic |
| `services/kapowarr.py` | Encapsulates Kapowarr library inspection, connection checks, and download requests |
| `services/story_arc.py` | Encapsulates Story Arc search, detail parsing, and library fixing operations |
| `services/metadata.py` | Provider routing, scrape single URLs, merge multi-URL |
| `services/processing.py` | File discovery, CBR conversion, embed_and_track |
| `pipeline/resolver.py` | Two-phase identity resolution: `resolve_identity` → `retrieve_metadata` |
| `pipeline/confidence.py` | Candidate pool evaluation, score-margin protection, and agreement bonus |
| `pipeline/dry_run.py` | In-memory SQLite context and archive write interception for true dry-run isolation |
| `writers/archive.py` | 9-step atomic archive writes with entry-by-entry CRC verification and directory fsync |
| `cache/jobs.py` | Durable SQLite queue with worker lease locking and poison-pill limit recovery |
| `observability/` | Structured logging, metrics counters, rate limiting, and retry policies |

---

## Architectural Invariants

1. **No live network in unit tests** — all provider calls are mocked.
2. **No archive modification without entry-level CRC verification** — `embed_comicinfo_in_cbz` always runs `verify_cbz_archive` before and after `os.replace`.
3. **No deletion of original CBR until CBZ is fully verified** — enforced in `converters/cbr_to_cbz.py`.
4. **Dry-run mode must never modify files or disk databases** — enforced via `pipeline/dry_run.py`.
5. **API routes never call providers directly** — static AST testing guarantees 0 provider imports in `api/*.py`.
6. **Issue numbers never use raw `int()`** — sorting and parsing always use `pipeline/issue_order.py`.

---

## Failure Modes

| Failure | Handler |
|---|---|
| `ArchiveReadError` | Raised before temp file is created — original is safe |
| `ArchiveWriteError` | Temp file deleted on exception — original is safe |
| `ArchiveValidationError` | Raised if CRC or XML verify fails — original is safe |
| Provider timeout / 429 | `RetryableError` — retried with exponential backoff |
| Provider 404 / 401 / Parse | `NonRetryableError` — never retried, gracefully classified |
| Worker process crash | Expired lease reclaimed automatically on startup or next worker cycle |
| Poison pill job | Transitions to `FAILED` with `error_code='MAX_ATTEMPTS_EXCEEDED'` after 3 attempts |
