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
├── test_api_boundary.py                   — Phase 49: Static AST analysis guaranteeing 0 provider imports in api/*.py
├── test_archive_transaction_hardening.py  — Phase 47: 9-step atomic transaction & CRC verification failure-injection
├── test_automation_self_write_protection.py — Phase 51: SHA256 loop protection & watcher restart idempotency
├── test_cache.py                          — CacheManager: SQLite operations, TTL, schema_version, invalidation
├── test_comicvine.py                      — ComicVine scraper: normal, 404, Cloudflare, empty volume
├── test_config.py                         — Config loader: YAML, env override, defaults
├── test_dry_run_isolation.py              — Phase 50: In-memory SQLite & deep filesystem snapshot verification
├── test_end_to_end_resolution_matrix.py   — Phase 52: 15-case end-to-end resolution matrix (Cases A through O)
├── test_failure_injection.py              — Phase 38: Failure simulation asserting original archives remain safe
├── test_filename_parser.py                — ParsedFilename for standard + edge-case filenames
├── test_fuzz_property.py                  — Phase 39: Adversarial input corpus; never-crash property
├── test_gcp.py                            — GCD scraper: normal, missing page, multi-URL merge
├── test_integration_pipeline.py           — Phase 37: Full pipeline with mocked providers
├── test_invariants.py                     — Permanent invariant regression assertions
├── test_job_queue_concurrency.py          — Phase 48: Multi-worker SQLite lease locking, recovery, and poison pills
├── test_kapowarr.py                       — Kapowarr REST API: series, issues, library status, offline
├── test_large_library.py                  — Phase 44: High-volume 45-case simulated library validation
├── test_merge.py                          — Pipeline field-level merge policy
├── test_observability.py                  — Phase 33–36: Logging, metrics, rate limiter, retry
├── test_performance_optimization.py       — Phase 43: Fast SHA256 buffer, SQLite WAL, ZIP stream copy
├── test_performance_validation.py         — Phase 53: 10, 100, 1000, 10000 file scale benchmarks
└── test_scoring.py                        — Confidence scoring and decision thresholds
```

---

## Running Tests

```bash
# All tests (Full discovery)
./venv/bin/python -m unittest discover tests

# Single module
./venv/bin/python -m unittest tests.test_end_to_end_resolution_matrix -v

# Performance benchmarks
./venv/bin/python -m unittest tests.test_performance_validation -v
```

---

## Invariants

1. **No live network** — all provider HTTP calls are mocked. No test makes real external HTTP requests.
2. **No persistent side effects** — tests clean up all temp files and SQLite databases in `tearDown`.
3. **Every archive write path has failure-injection tests** asserting original archives are 100% safe and unmodified.
4. **AST Static Analysis** — `tests/test_api_boundary.py` statically enforces zero provider imports in `api/*.py`.
5. **No raw `int()` on issue strings** — sorting and parsing always use `pipeline/issue_order.py`.
