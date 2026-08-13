# Production Release Checklist — ComicInfo Generator

This checklist must be reviewed and satisfied before deploying `comicinfo-generator` to production or running against a live library.

---

## 1. Codebase & CI Health

- [x] **Working tree clean**: All changes committed and pushed to `main`.
- [x] **GitHub Actions CI passing**: Workflows run on native Node 24 (`actions/checkout@v5`, `actions/setup-python@v6`) across supported Python versions.
- [x] **Full test suite passing**: All 311+ automated unit and integration tests passing (`python -m unittest discover tests`).
- [x] **Zero unexpected skips**: Test suite runs completely offline with fixture data; zero live network dependencies in test assertions.

---

## 2. Archive Safety & Durability

- [x] **10-Step atomic transactions verified**: All CBZ modifications execute `temp file -> fsync file -> fsync dir -> os.replace -> fsync dir -> verify` in the target directory (`test_archive_transaction_hardening.py`).
- [x] **Non-ComicInfo preservation**: 100% byte-for-byte SHA256 entry hash preservation across all original images, pages, and scanner assets (`test_metadata_write_safety_gate.py`).
- [x] **Failure injection resilience**: Simulated write and storage I/O errors (`EIO`, `ENOSPC`, `EROFS`) abort cleanly, leaving original archives byte-for-byte untouched (`test_failure_injection.py`).
- [x] **CBR to CBZ safety**: Original `.cbr` archives are deleted only after the new `.cbz` passes post-embed verification.

---

## 3. Metadata & Identity Safety

- [x] **Identity $\ne$ Metadata decoupling**: Candidate identity resolution (`ComicIdentity`) is strictly separate from metadata retrieval (`MetadataRetrievalResult`).
- [x] **Fail-safe write gating**: Only `METADATA_FOUND` with confidence $\ge 85$ triggers automatic writes. `METADATA_PARTIAL`, `METADATA_NOT_FOUND`, `METADATA_PROVIDER_ERROR`, and `METADATA_INVALID` strictly prevent write transactions.
- [x] **Issue number preservation**: Non-integer issue designations (`0.5`, `1A`, `Annual`, `Special`, `½`) are handled via `parse_issue_order()`.

---

## 4. CLI Dry-Run & Automation

- [x] **Zero-mutation dry-run**: `python main.py --dry-run <path>` evaluates libraries with 0 archive writes, 0 temp files, and 0 database writes (`test_cli_dry_run_integration.py`).
- [x] **Self-write loop protection**: Monitored directory watcher ignores self-generated writes via SHA256 tracking (`test_automation_self_write_protection.py`).
- [x] **Application restart idempotency**: Restarting the application skips previously processed, unchanged archives (`test_automation_production_test.py`).
- [x] **Durable job lease locking**: Concurrent workers acquire exclusive `BEGIN IMMEDIATE` leases; crashed workers trigger bounded retry recovery without poison-pill loops (`test_job_queue_concurrency.py`).

---

## 5. Security & Configuration

- [x] **Secret masking**: API keys and tokens are automatically masked in logs, JSON responses, and debug exports (`config.py`).
- [x] **Production configuration validation**: Invalid configurations, unparseable URLs, and missing extraction binaries raise actionable errors on startup (`test_production_config_hardening.py`).
- [x] **Deterministic dependencies**: Release dependencies are pinned in `requirements.txt` and verified in a fresh virtual environment.
- [x] **Default log level**: Standard `INFO` level enabled by default; debug traces disabled unless explicitly requested.

---

## 6. Documentation & Pre-Run Validation

- [x] **README synchronized**: Documents actual repository architecture, CLI flags, configuration, safety guarantees, and limitations.
- [x] **Architecture specs synchronized**: `docs/` files accurately reflect current implementation without obsolete phase-history notes.
- [x] **Gradual production validation verified**: Isolated batches (5 -> 25 -> 100 archives) verified with entry-by-entry SHA256 integrity checks.
- [ ] **Library backup**: Take a full backup or snapshot of target comic library prior to the initial automated batch run.
