# Actual Provider Contracts — ComicInfo Generator

## 1. Overview

All metadata providers implement the `BaseProvider` abstract class defined in [`providers/base.py`](file:///home/m3tal/apps/comicinfo-generator/providers/base.py).

---

## 2. Abstract Base Class (`BaseProvider`)

```python
class BaseProvider(ABC):
    @abstractmethod
    def get_name(self) -> str: ...

    @abstractmethod
    def search_series(self, query: str) -> list[dict]: ...

    @abstractmethod
    def search_issue(self, query: str) -> list[dict]: ...

    @abstractmethod
    def lookup_volume(self, volume_id: str) -> tuple[str, dict[str, str], list[dict]]: ...

    @abstractmethod
    def lookup_issue(self, issue_id: str) -> Optional[Comic]: ...
```

---

## 3. Provider Implementations

### 3.1 Kapowarr Provider (`providers/kapowarr.py`)
- **Name**: `Kapowarr`
- **Interface**: Interacts with Kapowarr REST API endpoints:
  - `GET /api/volumes` — List monitored volumes on Kapowarr server.
  - `GET /api/system/tasks` — Connection check.
- **Disk Scanning**: Scans configured local comic series directories to discover local CBZ/CBR files, cross-referencing whether valid `ComicInfo.xml` exists on disk.
- **Caching**: Saves library status to SQLite `search_cache` table under `Kapowarr/library`.

### 3.2 Comic Vine Provider (`providers/comicvine.py`)
- **Name**: `CV`
- **Interface**: HTML web scraper with Cloudflare bypass support via `cloudscraper` and `curl_cffi`.
- **Functions**:
  - `fetch_html(url)`: Fetches HTML using user-agent impersonation.
  - `parse_html(html_text, url)`: Extracts H1 series/number, og:title, wiki-descriptor publisher, store/cover date, summary, creator credits, characters, teams, and story arcs into a `Comic` model.
  - `scrape_issue(url, use_cache=True)`: Fetches and parses issue page, caching results in SQLite `issue_cache`.
  - `scrape_volume(volume_url, max_pages_limit=50, use_cache=True)`: Scrapes volume pages (`/4050-XXXXX/`), extracting issue URLs while applying slug filtering to reject TPBs/collected editions. Caches series data in `series_cache`.
  - `search_comicvine(query, search_type="all", use_cache=True)`: Searches Comic Vine search index, caching results in `search_cache`.

### 3.3 Grand Comics Database Provider (`providers/gcp.py`)
- **Name**: `GCP`
- **Interface**: Scrapes `comics.org` web pages and parses pasted GCP issue text.
- **Functions**:
  - `parse_gcp_text_refined(text, url)`: Parses copied text containing field labels (`Pencils:`, `Script:`, `Inks:`, `Characters:`, `Table of Contents`).
  - `scrape_gcp_issue(url_or_text, use_cache=True)`: Scrapes GCP API/archive HTML or parses raw text into a `Comic` model, caching in SQLite `issue_cache`.
  - `scrape_gcp_volume(volume_url)`: Scrapes GCP series page (`/series/XXXXX/`).
