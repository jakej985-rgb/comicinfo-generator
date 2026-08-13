# Testing — ComicInfo Generator

## Purpose

Describes the test strategy, directory layout, categories, and invariants  
for all automated tests in `comicinfo-generator`.

**All tests must pass before any commit to `main`.**

---

## Test Directory Layout

```text
tests/
├── fixtures/
│   ├── comicvine/        — HTML fixture pages for CV scraper tests
│   └── gcp/              — HTML fixture pages for GCD scraper tests
│
├── test_cache.py         — CacheManager: SQLite operations, TTL, schema_version, invalidation
├── test_comicvine.py     — ComicVine scraper: normal, 404, Cloudflare, empty volume
├── test_config.py        — Config loader: YAML, env override, defaults
├── test_filename_parser.py — ParsedFilename for standard + edge-case filenames
├── test_gcp.py           — GCD scraper: normal, missing page, multi-URL merge
├── test_integration_pipeline.py — Phase 37: full pipeline with mocked providers
├── test_failure_injection.py    — Phase 38: every failure mode; assert original safe
├── test_fuzz_property.py        — Phase 39: adversarial input corpus; never-crash property
├── test_kapowarr.py      — Kapowarr REST API: series, issues, library status, offline
├── test_merge.py         — Pipeline field-level merge policy
├── test_observability.py — Phase 33–36: logging, metrics, rate limiter, retry
└── test_scoring.py       — Confidence scoring and decision thresholds
```

---

## Test Categories

### Unit Tests
- Isolated to a single module.
- All external I/O mocked (network, filesystem, SQLite).
- Fast (< 50ms each).

### Integration Tests (`test_integration_pipeline.py`)
- Exercise the full pipeline: CBZ → identity → providers → ComicInfo → archive → state.
- Providers are mocked — no live network.
- Use temporary directories created by `tempfile.mkdtemp()`.
- Always clean up in `tearDown`.

### Failure-Injection Tests (`test_failure_injection.py`)
- Every test simulates a specific failure (permission, timeout, 429, disk full, etc.).
- Every test asserts: **original archive exists and is unchanged after the failure**.
- Every test asserts: the appropriate typed exception was raised.

### Property / Fuzz Tests (`test_fuzz_property.py`)
- Tests the "never crash" invariant across large adversarial input corpora.
- Covers: filenames, issue numbers, XML generation, archive contents.
- No mocking — exercises real parsers with real adversarial inputs.
- Uses `subTest` so every corpus entry is independently reported.

---

## Running Tests

```bash
# All tests
./venv/bin/python -m unittest discover tests

# Single module
./venv/bin/python -m unittest tests.test_integration_pipeline -v

# Fuzz tests only
./venv/bin/python -m unittest tests.test_fuzz_property -v
```

---

## Invariants

1. **No live network** — all provider HTTP calls are mocked. No test should make a real HTTP request.
2. **No persistent side effects** — tests clean up all temp files and SQLite databases.
3. **Every archive operation has a failure-injection test** that asserts original-safe behaviour.
4. **Every identity-resolution change requires a new test** in `test_integration_pipeline.py`.
5. **Parser changes require fuzz corpus expansion** in `test_fuzz_property.py`.

---

## Fixture Management

HTML fixtures for provider scraper tests live in `tests/fixtures/`:

```bash
# Regenerate a fixture from a live page (run manually, commit the result)
curl -s "https://comicvine.gamespot.com/batman/4000-123456/" > tests/fixtures/comicvine/batman_001.html
```

Once committed, fixtures are static — no fixture fetches live data during CI.

---

## Failure Modes

| Problem | What to check |
|---|---|
| A test makes a live HTTP request | Add `@patch("providers.comicvine.urllib.request.urlopen", ...)` |
| A temp file leaks between tests | Ensure `tearDown` calls `shutil.rmtree(self.tmp)` |
| Fuzz test fails on random seed | Check `random.Random(42)` seed — it's deterministic |
| Integration test fails with `NoneType` | Check that the mock returns a `Comic`, not `None` |

---

## Testing Requirements by Phase

| Phase | Requirement |
|---|---|
| Any identity-resolution change | Add test to `test_integration_pipeline.py` |
| Any archive-writing change | Add test to `test_failure_injection.py` |
| Any parser change | Expand corpus in `test_fuzz_property.py` |
| Any provider change | Add fixture HTML, update scraper test |
| Any cache schema change | Update `test_cache.py` with new schema version |

---

## Do-Not-Do Rules

- Do not write tests that depend on live internet access.
- Do not write tests that leave temp files on disk after completion.
- Do not test implementation details — test observable outputs and side effects.
- Do not skip failure-injection tests for "obvious" code paths.
- Do not mock `os.path.exists` unless specifically testing file-not-found paths.
