# Actual Testing Baseline — ComicInfo Generator

## 1. Test Suite Framework

The repository uses Python's standard `unittest` framework.

Execution command:
```bash
./venv/bin/python -m unittest discover tests
```

---

## 2. Baseline Test Execution Results

As of baseline setup (2026-08-13):

```text
Ran 7 tests in 0.747s
OK
```

### Test Breakdown

1. `tests/test_config.py`
   - `test_default_config_loading`: Verifies loading default `Config` values.
   - `test_custom_yaml_config`: Verifies overriding options from YAML files.

2. `tests/test_cache.py`
   - `test_cache_manager_init`: Verifies SQLite schema creation (`series_cache`, `issue_cache`, `search_cache`, `file_hashes`).
   - `test_file_hash_tracking`: Verifies saving and retrieving `file_hashes` records.
   - `test_issue_caching`: Verifies storing and retrieving `Comic` objects in `issue_cache`.
   - `test_search_caching`: Verifies storing and retrieving search queries in `search_cache`.

3. `tests/test_kapowarr.py`
   - `test_kapowarr_provider_init`: Verifies `KapowarrProvider` initialization and header generation.

---

## 3. Test Coverage Gaps & Missing Test Cases

The following components currently lack automated unit test coverage:

- **Archive Safety (`writers/archive.py`)**: No tests verifying atomic ZIP creation, permissions errors, or corrupt ZIP handling.
- **ComicInfo Losslessness (`writers/comicinfo.py` & `pipeline/resolver.py`)**: No round-trip tests (`XML -> Comic -> XML`).
- **Scraping Parsers (`providers/comicvine.py` & `providers/gcp.py`)**: No fixture-based offline parser tests for HTML scraping.
- **Identity Resolver (`pipeline/resolver.py`)**: No confidence scoring or provider hierarchy unit tests.
- **CBR Conversion (`converters/cbr_to_cbz.py`)**: No extraction/conversion unit tests.
