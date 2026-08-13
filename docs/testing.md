# Testing — ComicInfo Generator

## Purpose

Describes the test strategy, directory layout, test suites, and invariants  
for all automated tests in `comicinfo-generator`.

**All tests must pass before any commit to `main`.**

---

## Test Directory Layout

```text
tests/
├── fixtures/
│   ├── comicvine/                         — HTML fixture pages for CV scraper tests
│   └── gcp/                               — HTML fixture pages for GCD scraper tests
│
├── test_api_boundary.py                   — Static AST analysis guaranteeing zero provider imports in api/*.py
├── test_archive_safety.py                 — Archive read/write and rollback checks
├── test_archive_transaction_hardening.py  — 10-step atomic transaction & CRC verification failure-injection
├── test_automation_self_write_protection.py — SHA256 loop protection & watcher restart idempotency
├── test_automation_stress.py              — Self-write avoidance, restart state persistence, and burst deduplication
├── test_cache.py                          — CacheManager: SQLite operations, TTL, schema_version, invalidation
├── test_canonical_identity_key.py         — Canonical identity comparisons across complex issue number strings
├── test_cli_dry_run_integration.py        — Subprocess CLI dry-run evaluation with 0 disk and database mutations
├── test_comicvine.py                      — ComicVine scraper: normal, 404, Cloudflare, empty volume
├── test_config.py                         — Config loader: YAML, env override, defaults, strict archive verification
├── test_dry_run_isolation.py              — In-memory SQLite & deep filesystem snapshot verification
├── test_durability_fsync.py               — fsync status classification (SUCCESS, UNSUPPORTED, FAILED) & I/O failure handling
├── test_end_to_end_resolution_matrix.py   — 15-case end-to-end resolution matrix (Cases A through O)
├── test_failure_injection.py              — Failure simulation asserting original archives remain safe
├── test_filename_parser.py                — ParsedFilename for standard + edge-case filenames
├── test_fuzz_property.py                  — Adversarial input corpus; never-crash property
├── test_gcp.py                            — GCD scraper: normal, missing page, multi-URL merge
├── test_identity_authority_and_conflicts.py — Conflict categorization & XML-provider disagreement detection
├── test_integration_pipeline.py           — Full pipeline with mocked providers
├── test_invariants.py                     — Permanent invariant regression assertions
├── test_job_queue_concurrency.py          — Multi-worker SQLite lease locking, recovery, and poison pills
├── test_jobs.py                           — JobStore basics, status updates, and restart safety
├── test_kapowarr.py                       — Kapowarr REST API: series, issues, library status, offline
├── test_large_library.py                  — High-volume 45-case simulated library validation
├── test_merge.py                          — Pipeline field-level merge policy
├── test_metadata_write_safety_gate.py     — Metadata retrieval state write gate & non-ComicInfo entry preservation
├── test_multi_worker_stress.py            — Parallel workers against concurrent jobs, crash recovery, and poison pills
├── test_observability.py                  — Logging, metrics, rate limiter, retry
├── test_performance_optimization.py       — Fast SHA256 buffer, SQLite WAL, ZIP stream copy
├── test_performance_validation.py         — File scale benchmarks and memory bounds
├── test_production_config_hardening.py    — Startup configuration validation, secret masking, and safe defaults
├── test_provider_failure_propagation.py   — Provider failure state survival to final ResolutionResult
├── test_real_library_validation.py        — End-to-end real library validation across 15 archive scenarios
├── test_scoring.py                        — Confidence scoring and decision thresholds
└── test_strict_archive_integrity.py       — Strict SHA256 entry manifest verification mode
```

---

## Running Tests

```bash
# All tests (Full discovery)
./venv/bin/python -m unittest discover tests

# Single module
./venv/bin/python -m unittest tests.test_real_library_validation -v

# Concurrency and stress benchmarks
./venv/bin/python -m unittest tests.test_multi_worker_stress -v
```

---

## Invariants

1. **No live network** — all provider HTTP calls are mocked. No test makes real external HTTP requests.
2. **No persistent side effects** — tests clean up all temp files and SQLite databases in `tearDown`.
3. **Every archive write path has failure-injection tests** asserting original archives are 100% safe and unmodified.
4. **AST Static Analysis** — `tests/test_api_boundary.py` statically enforces zero provider imports in `api/*.py`.
5. **No raw `int()` on issue strings** — sorting and parsing always use `pipeline/issue_order.py`.
