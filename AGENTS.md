# AGENTS.md — AI Coding Agent Rules for comicinfo-generator

This file defines explicit rules for AI coding agents working on this repository.  
These rules exist because multiple AI agents and human contributors may work on this codebase.  
They encode hard-won invariants that must not be broken.

**Read this file before making any change. Follow every rule without exception.**

---

## 1. Architecture Rules

### 1.1 Do not rewrite the application from scratch.
This repository has accumulated significant domain logic (issue ordering, identity resolution,
confidence scoring, atomic archive writes, CBR safety, durable job queuing).  
Rewriting from scratch discards tested invariants. Always extend, never replace.

### 1.2 Do not bypass the identity resolver.
All metadata retrieval must go through `pipeline/resolver.py → MetadataResolver`.  
Do not call providers directly from `api/handlers.py`, `services/`, or any other layer.

### 1.3 Do not accept the first provider search result automatically.
Every candidate must be scored by `pipeline/scoring.py` and evaluated by
`pipeline/confidence.py`. A result with confidence < 70 must not be auto-embedded.

### 1.4 Do not add provider-specific fields to domain models.
`models/comic.py` and `models/identity.py` are domain models.  
Comic Vine IDs, GCD slugs, Kapowarr internal IDs — none of these belong there.  
Use `provider_id` (generic) and `provider_name` (string) only.

### 1.5 Do not put business logic in `api/handlers.py`.
Handlers route requests and delegate to `services/`. All logic lives in `services/`,
`pipeline/`, `providers/`, or `writers/`.

---

## 2. Archive Safety Rules

### 2.1 Do not modify archives without archive verification.
Every call to `embed_comicinfo_in_cbz` runs `verify_cbz_archive` before and after
`os.replace`. Never bypass or remove these checks.

### 2.2 Do not delete the original `.cbr` until the converted `.cbz` is verified.
`converters/cbr_to_cbz.py` enforces this. The CBR is deleted only after:
1. The CBZ has been written
2. `verify_cbz_archive` has passed
3. ComicInfo.xml has been embedded
4. Post-embed verification has passed

### 2.3 Do not write directly to the target archive.
Always use the `temp file → fsync → os.replace` pattern in `writers/archive.py`.
The temp file must be in the **same directory** as the target (same filesystem).

### 2.4 Do not suppress archive exceptions.
`ArchiveReadError`, `ArchiveWriteError`, and `ArchiveValidationError` must always
propagate. Log the failure, record the job as `FAILED`, but do not swallow the error.

---

## 3. Provider Rules

### 3.1 Do not silently swallow provider exceptions.
All provider failures must raise typed exceptions:
- `RetryableError` for timeouts, 429, temporary 5xx
- `NonRetryableError` for 404, 401/403, Cloudflare blocks, parse failures

Never catch and discard a provider exception without logging.

### 3.2 Do not retry non-retryable errors.
HTTP 404 and authentication failures must never be retried.  
Use `observability/retry.py → is_retryable_exception()` to classify.

### 3.3 Do not make live HTTP requests in tests.
All provider tests must mock network calls. Fixture HTML lives in `tests/fixtures/`.

### 3.4 Respect rate limits.
All external provider HTTP calls must acquire a token from `observability/rate_limiter`
before firing. Never bypass rate limiting for "just one request".

---

## 4. Kapowarr Rules

### 4.1 Do not change Kapowarr ownership or permissions.
Kapowarr manages its own file ownership. Never call `os.chown` on Kapowarr-owned files.
`writers/archive.py → preserve_file_metadata` uses best-effort preservation only
and silently skips on permission errors — do not change this.

### 4.2 Do not assume Kapowarr is always online.
`KapowarrProvider.test_connection()` must be called before any Kapowarr operation.
The pipeline must gracefully fall back to Comic Vine / GCD if Kapowarr is offline.

---

## 5. ComicInfo.xml Rules

### 5.1 Do not remove unknown ComicInfo fields.
If an existing `ComicInfo.xml` contains fields that are not in the current `Comic`
dataclass, they must be preserved during re-embed. Do not strip unrecognised tags.

### 5.2 Do not invent schema extensions.
`ComicInfo.xml` follows the published schema. Do not add custom tags or attributes
that break compatibility with Kavita, Komga, Komf, and other readers.

---

## 6. Automation Rules

### 6.1 Do not re-process files the pipeline itself just wrote.
The self-write guard in `automation/watcher.py` uses SHA256 fingerprinting.
Do not modify `cache/tracker.py → mark_file_processed` in ways that break this.

### 6.2 Dry-run mode must never modify any file.
When `--dry-run` is active, no archive, temp file, file hash, or job record  
may be created or modified. This is enforced in `main.py`.

---

## 7. Issue Number Rules

### 7.1 Do not use `int()` on issue numbers.
Issue numbers include `"0.5"`, `"1A"`, `"Annual"`, `"Special"`, `"½"`.  
Always use `pipeline/issue_order.py → parse_issue_order()` for parsing and sorting.

---

## 8. Testing Rules

### 8.1 Every identity-resolution change requires tests.
Any change to `pipeline/resolver.py`, `pipeline/confidence.py`, `pipeline/scoring.py`,
or `pipeline/filename_parser.py` must include new or updated tests in  
`tests/test_integration_pipeline.py`.

### 8.2 Every archive-writing change requires safety tests.
Any change to `writers/archive.py` or `converters/cbr_to_cbz.py` must include  
a failure-injection test in `tests/test_failure_injection.py` that asserts the  
original archive is safe after the failure.

### 8.3 Parser changes require fuzz corpus expansion.
Any change to `pipeline/filename_parser.py` or `pipeline/issue_order.py` must  
add adversarial inputs to `tests/test_fuzz_property.py` covering the new behaviour.

### 8.4 All tests must pass before merging.
Run `./venv/bin/python -m unittest discover tests` and confirm `OK` before committing.

---

## 9. What to Do When Uncertain

1. Read the relevant `docs/` document for the module area you are changing.
2. Check `plan.md` for the phase that implemented the behaviour you are modifying.
3. Run the tests — if they fail, your change broke an invariant.
4. If the change is large or architectural, create an implementation plan and request human review before proceeding.

---

## 10. Summary of Never-Do Actions

| Rule | Never Do This |
|---|---|
| Architecture | Rewrite from scratch |
| Identity | Bypass `MetadataResolver` |
| Identity | Auto-accept the first search result |
| Archives | Write to target without temp+verify+replace |
| Archives | Delete CBR before CBZ is verified |
| Archives | Silently catch `ArchiveError` |
| Providers | Silently swallow provider exceptions |
| Providers | Retry HTTP 404 or auth failures |
| Kapowarr | Change file ownership/permissions |
| ComicInfo | Strip unrecognised XML fields |
| Automation | Let dry-run mode modify files |
| Automation | Re-process self-written files |
| API Layer | Import or call providers from `api/` directly |
| Issue Numbers | Use `int()` on issue strings |
| Testing | Write tests that make live HTTP requests |
