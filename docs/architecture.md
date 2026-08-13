# Actual Architecture — ComicInfo Generator

## 1. Overview

`jakej985-rgb/comicinfo-generator` is a Python-based metadata scraper, generator, and embedding engine designed to enrich comic book archives (`.cbz` and `.cbr`) with standard `ComicInfo.xml` metadata files. It integrates with **Kapowarr**, **Comic Vine (CV)**, and **Grand Comics Database (GCP/GCD)**.

The application serves a web interface (built with Vanilla JS + glassmorphic dark theme CSS) backed by a Python standard library `http.server` backend in `app.py`.

---

## 2. Directory & Module Structure

```text
comicinfo-generator/
├── app.py                     # HTTP server request handler & REST endpoints
├── main.py                    # Entry point launching app.py web server
├── config.py                  # YAML/Environment configuration loader (~/.comicinfo/config.yaml)
│
├── models/
│   └── comic.py               # Core `Comic` dataclass and `merge_comics()` function
│
├── providers/
│   ├── base.py                # Abstract BaseProvider interface
│   ├── kapowarr.py            # Kapowarr REST API provider & disk scanner
│   ├── comicvine.py           # Comic Vine HTML scraper, issue/volume scraper & slug matcher
│   ├── gcp.py                 # Grand Comics Database scraper & page text parser
│   └── story_arc.py           # Story arc tracker, custom reading order parser & issue matcher
│
├── pipeline/
│   └── resolver.py            # MetadataResolver hierarchy & existing ComicInfo.xml parser
│
├── cache/
│   ├── db.py                  # CacheManager handling SQLite (~/.comicinfo/cache.db)
│   └── tracker.py             # SHA256 file fingerprinting & mark_file_processed()
│
├── writers/
│   ├── comicinfo.py           # Lxml-based ComicInfo.xml generator
│   └── archive.py             # Atomic CBZ ZIP updater & permission takeover fallback
│
├── automation/
│   └── queue.py               # In-memory ThreadPoolExecutor TaskQueue
│
├── converters/
│   └── cbr_to_cbz.py          # CBR (RAR) to CBZ (ZIP) conversion module
│
├── static/
│   ├── index.html             # Single-page web interface (Tabbed layout)
│   ├── style.css              # Custom CSS design system (Dark mode glassmorphism)
│   └── app.js                 # Frontend interactions & API bindings
│
└── tests/                     # Unit test suites (unittest)
    ├── test_cache.py
    ├── test_config.py
    └── test_kapowarr.py
```

---

## 3. Core Data Flow

```text
User Request (Web UI or API)
         │
         ▼
┌──────────────────┐
│   app.py Server  │  Receives route request (/api/embed, /api/batch-embed, /api/search)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ MetadataResolver │  Evaluates priority:
└────────┬─────────┘  1. Existing ComicInfo.xml (unless overwrite=True)
         │            2. Direct URL / copied text override
         │            3. Kapowarr API lookup
         │            4. Comic Vine search & scrape
         │            5. GCP search & scrape
         │
         ▼
┌──────────────────┐
│   Comic Model    │  Normalizes issue or multi-issue TPB data into dataclass
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│   writers/       │  Generates XML bytes using lxml (writers/comicinfo.py)
│   archive.py     │  Atomic temporary ZIP swap & embed into target .cbz
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  cache/db.py     │  Records SHA256, file size, mtime & metadata to SQLite (~/.comicinfo/cache.db)
└──────────────────┘
```

---

## 4. Storage & Persistence

1. **Configuration File**: `~/.comicinfo/config.yaml`
   - Defines database paths, Kapowarr URL/API keys, ComicVine API keys, cache settings, and output options.
2. **SQLite Database**: `~/.comicinfo/cache.db`
   - Managed by `CacheManager` (`cache/db.py`).
   - Tables:
     - `series_cache` (provider, series_id, name, year, publisher, data_json, updated_at)
     - `issue_cache` (provider, issue_id, series_id, number, title, data_json, updated_at)
     - `search_cache` (provider, search_type, query, results_json, updated_at)
     - `file_hashes` (file_path, sha256, file_size, mtime, provider_used, metadata_version, processed_at)
