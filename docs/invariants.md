# Architectural Invariants — ComicInfo Generator

This document defines the core, permanent architectural invariants of `comicinfo-generator`.
These rules govern design decisions across all subsystems (pipeline, providers, archives, automation, and writers).

---

## 1. Identity Invariant

> **A filename is never sufficient proof of identity.**

- Filenames are ambiguous, noisy, and prone to user formatting variations (e.g. `Batman #1`, `Batman (2016) #001`, `Batman 1A`).
- Filenames provide **signals** (parsed into `ParsedFilename` via `pipeline/filename_parser.py`), which are used as inputs to generate candidates.
- Final identity MUST be confirmed by identity resolution (`pipeline/resolver.py → MetadataResolver`) and evaluated through confidence scoring (`pipeline/scoring.py` & `pipeline/confidence.py`).

---

## 2. Provider Invariant

> **Providers return candidates. Providers do not select the final identity.**

- `KapowarrProvider`, `ComicVineProvider`, and `GCPProvider` are candidate generators.
- Providers query external or local databases and return raw candidate identities.
- The pipeline (`pipeline/resolver.py` & `pipeline/scoring.py`) scores all candidates against identity signals and selects the best candidate based on explicit threshold rules (`AUTO_ACCEPT`, `MANUAL_REVIEW`, `UNRESOLVED`).

---

## 3. Metadata Invariant

> **Identity and metadata are separate concepts.**

- `ComicIdentity` (`models/identity.py`) represents *what* a comic is (series, issue number, volume ID, publication year, publisher, provider ID).
- `Comic` (`models/comic.py`) represents *metadata details* (title, summary, creators, characters, story arcs, cover art info).
- Identity resolution (`resolve_identity()`) happens strictly BEFORE metadata retrieval (`retrieve_metadata()`). Metadata is fetched only after an identity candidate is selected.

---

## 4. Archive Safety Invariant

> **Never replace an original archive with an unverified archive.**

- Every archive update (`writers/archive.py → embed_comicinfo_in_cbz`) uses the atomic swap pattern: `temp file → fsync → os.replace`.
- Pre-replacement verification (`verify_cbz_archive`) tests the temporary archive for ZIP integrity, image preservation, and parseable `ComicInfo.xml` BEFORE replacing the original.
- Post-replacement verification runs on the final file. If any check fails, the transaction is aborted and the original archive remains untouched.
- Conversion from `.cbr` to `.cbz` (`converters/cbr_to_cbz.py`) deletes the original `.cbr` ONLY after the `.cbz` is created, embedded, and fully verified.

---

## 5. Existing Metadata Invariant

> **Existing valid metadata is never destroyed merely because new metadata exists.**

- Existing embedded `ComicInfo.xml` fields are parsed (`read_existing_comicinfo()`).
- Unless `force_overwrite` / `overwrite=True` is explicitly requested, existing metadata is preserved or merged using explicit field-level priority policies (`pipeline/merge.py`).
- Unrecognised XML elements in existing `ComicInfo.xml` files are preserved during re-embedding.

---

## 6. Automation Invariant

> **Every processing operation is restart-safe.**

- Job states (`PENDING`, `PROCESSING`, `DONE`, `FAILED`) are persisted in SQLite (`cache/jobs.py`).
- On application restart, stuck `PROCESSING` jobs are automatically reset to `PENDING`.
- File processing uses SHA256 fingerprinting (`cache/tracker.py` & `cache/db.py → file_hashes`).
- Re-running the pipeline or restarting the watcher will not cause duplicate embeds or re-processing of already processed, unchanged files.

---

## 7. Error Classification Invariant

> **No match != provider failure.**

- A provider search returning zero results for a query is a valid negative match (`None` or empty list), NOT a system failure or network error.
- Provider failures are reserved for network timeouts, rate limit breaches (HTTP 429), server errors (HTTP 5xx), and non-retryable errors (HTTP 404, auth failure, parse errors).
- Zero matches result in an `UNRESOLVED` identity decision, allowing graceful degradation or manual review without raising unhandled exceptions.

---

## 8. Kapowarr Preference Invariant

> **Kapowarr identity is preferred when it can be reliably associated with the archive.**

- When Kapowarr is online (`KapowarrProvider.test_connection() == True`), its series and issue IDs are given high priority because Kapowarr manages the user's local organized library.
- If Kapowarr is offline or fails to return a candidate, the pipeline seamlessly falls back to Comic Vine and GCD.

---

## Summary Matrix

| Invariant | Enforced In | Key Mechanism / Class |
|---|---|---|
| 1. Identity | `pipeline/filename_parser.py`, `pipeline/resolver.py` | `parse_filename_identity()` signal extraction |
| 2. Providers | `pipeline/resolver.py`, `pipeline/scoring.py` | Candidates gathered & scored independently |
| 3. Metadata | `pipeline/resolver.py`, `models/` | `resolve_identity()` vs `retrieve_metadata()` |
| 4. Archives | `writers/archive.py`, `converters/cbr_to_cbz.py` | `verify_cbz_archive()`, atomic `os.replace` |
| 5. Existing Metadata | `pipeline/merge.py`, `writers/comicinfo.py` | Field-level provenance & unrecognised tag preservation |
| 6. Automation | `cache/jobs.py`, `cache/tracker.py` | SQLite durable queue, SHA256 file hashes |
| 7. Errors | `observability/retry.py`, `pipeline/resolver.py` | Typed exceptions vs `UNRESOLVED` decisions |
| 8. Kapowarr | `pipeline/resolver.py`, `services/metadata.py` | Kapowarr connection test & preferred lookup |
