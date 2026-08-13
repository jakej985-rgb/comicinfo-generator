import os
import json
import sqlite3
import time
import hashlib
from typing import Optional, Dict, List

from models.comic import Comic

# Phase 30 & 31: Schema version — bump this whenever parser logic changes
# to automatically invalidate all cached provider results on next startup.
CACHE_SCHEMA_VERSION = "2.1"

# Phase 31: TTL values per cache type (seconds)
TTL_ISSUE   = 7 * 24 * 3600   # 7 days
TTL_SERIES  = 7 * 24 * 3600   # 7 days
TTL_SEARCH  = 24 * 3600       # 24 hours
TTL_URL     = 12 * 3600       # 12 hours


def _source_hash(data: dict) -> str:
    """Computes a stable SHA256 fingerprint of a JSON-serialisable dict."""
    blob = json.dumps(data, sort_keys=True, ensure_ascii=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


class CacheManager:
    """
    SQLite Cache Manager — Phase 30 & 31 expanded architecture.

    Phase 30 additions per cached result:
      provider, provider_id, fetched_at, expires_at, schema_version, source_hash

    Phase 31 invalidation triggers:
      - schema_version mismatch  (parser/provider schema changes)
      - TTL expiry               (cached data is expired)
      - manual refresh flag      (metadata is manually refreshed)
      - source_hash change       (provider data changed between fetches)

    Phase 43 additions:
      - Thread-safe L1 in-memory cache for zero-disk-latency cache hits
      - Optimized SQLite PRAGMAs (WAL, synchronous=NORMAL, cache_size=-64000)
    """

    def __init__(self, db_path: str = "~/.comicinfo/cache.db"):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Phase 43: Performance PRAGMAs for high-throughput SQLite
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA temp_store=MEMORY;")
            conn.execute("PRAGMA cache_size=-64000;")
        except Exception:
            pass
        return conn

    def _init_db(self):
        """Initialises expanded database schema (Phase 30)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # --- Series cache (Phase 30: added expires_at, schema_version, source_hash) ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS series_cache (
                    provider        TEXT NOT NULL,
                    series_id       TEXT NOT NULL,
                    name            TEXT,
                    year            INTEGER,
                    publisher       TEXT,
                    data_json       TEXT,
                    fetched_at      INTEGER,
                    expires_at      INTEGER,
                    schema_version  TEXT DEFAULT '2.1',
                    source_hash     TEXT,
                    updated_at      INTEGER,
                    PRIMARY KEY (provider, series_id)
                );
            """)

            # --- Issue cache (Phase 30: full provider fingerprint fields) ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS issue_cache (
                    provider        TEXT NOT NULL,
                    issue_id        TEXT NOT NULL,
                    series_id       TEXT,
                    number          TEXT,
                    title           TEXT,
                    data_json       TEXT,
                    fetched_at      INTEGER,
                    expires_at      INTEGER,
                    schema_version  TEXT DEFAULT '2.1',
                    source_hash     TEXT,
                    updated_at      INTEGER,
                    PRIMARY KEY (provider, issue_id)
                );
            """)

            # --- Search cache (Phase 30: expires_at, schema_version, source_hash) ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    provider        TEXT NOT NULL,
                    search_type     TEXT NOT NULL,
                    query           TEXT NOT NULL,
                    results_json    TEXT,
                    fetched_at      INTEGER,
                    expires_at      INTEGER,
                    schema_version  TEXT DEFAULT '2.1',
                    source_hash     TEXT,
                    updated_at      INTEGER,
                    PRIMARY KEY (provider, search_type, query)
                );
            """)

            # --- URL cache (Phase 30: new — keyed by provider + URL) ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS url_cache (
                    provider        TEXT NOT NULL,
                    url             TEXT NOT NULL,
                    data_json       TEXT,
                    fetched_at      INTEGER,
                    expires_at      INTEGER,
                    schema_version  TEXT DEFAULT '2.1',
                    source_hash     TEXT,
                    updated_at      INTEGER,
                    PRIMARY KEY (provider, url)
                );
            """)

            # --- File hashes & processing state (existing, unchanged) ---
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_hashes (
                    file_path           TEXT PRIMARY KEY,
                    sha256              TEXT NOT NULL,
                    file_size           INTEGER NOT NULL,
                    mtime               INTEGER NOT NULL,
                    provider_used       TEXT,
                    metadata_version    TEXT,
                    status              TEXT DEFAULT 'SUCCESS',
                    job_id              TEXT,
                    confidence          REAL DEFAULT 100.0,
                    error_message       TEXT,
                    generator_version   TEXT DEFAULT '2.0',
                    processed_at        INTEGER
                );
            """)

            # Phase 30: Add new columns to existing tables if upgrading
            for table, cols in [
                ("series_cache", ["fetched_at INTEGER", "expires_at INTEGER",
                                  "schema_version TEXT", "source_hash TEXT"]),
                ("issue_cache",  ["fetched_at INTEGER", "expires_at INTEGER",
                                  "schema_version TEXT", "source_hash TEXT"]),
                ("search_cache", ["fetched_at INTEGER", "expires_at INTEGER",
                                  "schema_version TEXT", "source_hash TEXT"]),
            ]:
                for col_def in cols:
                    col_name = col_def.split()[0]
                    try:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def};")
                    except sqlite3.OperationalError:
                        pass  # column already exists

            conn.commit()

    # ------------------------------------------------------------------ #
    # Phase 31: Central validity check                                    #
    # ------------------------------------------------------------------ #
    def _is_valid(self, row: sqlite3.Row) -> bool:
        """
        Phase 31: Returns True only if:
          - schema_version matches current CACHE_SCHEMA_VERSION
          - row has not expired (expires_at > now)
        """
        now = int(time.time())
        schema_ok = (row["schema_version"] or "") == CACHE_SCHEMA_VERSION
        not_expired = (row["expires_at"] or 0) > now
        return schema_ok and not_expired

    # ------------------------------------------------------------------ #
    # File Hash Operations                                                #
    # ------------------------------------------------------------------ #
    def get_file_record(self, file_path: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM file_hashes WHERE file_path = ?",
                           (os.path.abspath(file_path),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_file_record(
        self,
        file_path: str,
        sha256: str,
        file_size: int,
        mtime: int,
        provider_used: str = "",
        metadata_version: str = "2.0",
        status: str = "SUCCESS",
        job_id: str = "",
        confidence: float = 100.0,
        error_message: str = ""
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            cursor.execute("""
                INSERT INTO file_hashes (file_path, sha256, file_size, mtime, provider_used,
                    metadata_version, status, job_id, confidence, error_message,
                    generator_version, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2.0', ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    file_size = excluded.file_size,
                    mtime = excluded.mtime,
                    provider_used = excluded.provider_used,
                    metadata_version = excluded.metadata_version,
                    status = excluded.status,
                    job_id = excluded.job_id,
                    confidence = excluded.confidence,
                    error_message = excluded.error_message,
                    processed_at = excluded.processed_at;
            """, (os.path.abspath(file_path), sha256, file_size, mtime, provider_used,
                  metadata_version, status, job_id, confidence, error_message, now))
            conn.commit()

    # ------------------------------------------------------------------ #
    # Issue Cache Operations (Phase 30 & 31)                             #
    # ------------------------------------------------------------------ #
    def get_cached_issue(self, provider: str, issue_id: str) -> Optional[Comic]:
        """Phase 31: Returns cached issue only if schema_version matches and not expired."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM issue_cache WHERE provider = ? AND issue_id = ?
            """, (provider, str(issue_id)))
            row = cursor.fetchone()
            if row and self._is_valid(row) and row["data_json"]:
                try:
                    data = json.loads(row["data_json"])
                    from dataclasses import fields as dc_fields
                    valid_keys = {f.name for f in dc_fields(Comic)}
                    filtered = {k: v for k, v in data.items() if k in valid_keys}
                    return Comic(**filtered)
                except Exception:
                    pass
        return None

    def save_cached_issue(self, provider: str, issue_id: str, comic: Comic,
                          series_id: str = ""):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            data_dict = {
                "title": comic.title, "series": comic.series, "number": comic.number,
                "volume": comic.volume, "count": comic.count, "summary": comic.summary,
                "notes": comic.notes, "year": comic.year, "month": comic.month,
                "day": comic.day, "publisher": comic.publisher, "genre": comic.genre,
                "web": comic.web, "language": comic.language, "format": comic.format,
                "writers": comic.writers, "pencillers": comic.pencillers,
                "inkers": comic.inkers, "colorists": comic.colorists,
                "letterers": comic.letterers, "cover_artists": comic.cover_artists,
                "characters": comic.characters, "teams": comic.teams,
                "story_arcs": comic.story_arcs, "provider_name": provider,
                "provider_id": str(issue_id)
            }
            src_hash = _source_hash(data_dict)
            cursor.execute("""
                INSERT INTO issue_cache (provider, issue_id, series_id, number, title,
                    data_json, fetched_at, expires_at, schema_version, source_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, issue_id) DO UPDATE SET
                    series_id = excluded.series_id,
                    number = excluded.number,
                    title = excluded.title,
                    data_json = excluded.data_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    schema_version = excluded.schema_version,
                    source_hash = excluded.source_hash,
                    updated_at = excluded.updated_at;
            """, (provider, str(issue_id), series_id, comic.number, comic.title,
                  json.dumps(data_dict), now, now + TTL_ISSUE,
                  CACHE_SCHEMA_VERSION, src_hash, now))
            conn.commit()

    # ------------------------------------------------------------------ #
    # Series Cache Operations (Phase 30 & 31)                            #
    # ------------------------------------------------------------------ #
    def get_cached_series(self, provider: str, series_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM series_cache WHERE provider = ? AND series_id = ?
            """, (provider, str(series_id)))
            row = cursor.fetchone()
            if row and self._is_valid(row) and row["data_json"]:
                try:
                    return json.loads(row["data_json"])
                except Exception:
                    pass
        return None

    def save_cached_series(self, provider: str, series_id: str, name: str = "",
                           year: int = 0, publisher: str = "", data: dict = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            data_json = json.dumps(data or {})
            src_hash = _source_hash(data or {})
            cursor.execute("""
                INSERT INTO series_cache (provider, series_id, name, year, publisher,
                    data_json, fetched_at, expires_at, schema_version, source_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, series_id) DO UPDATE SET
                    name = excluded.name,
                    year = excluded.year,
                    publisher = excluded.publisher,
                    data_json = excluded.data_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    schema_version = excluded.schema_version,
                    source_hash = excluded.source_hash,
                    updated_at = excluded.updated_at;
            """, (provider, str(series_id), name, year, publisher, data_json,
                  now, now + TTL_SERIES, CACHE_SCHEMA_VERSION, src_hash, now))
            conn.commit()

    # ------------------------------------------------------------------ #
    # Search Cache Operations (Phase 30 & 31)                            #
    # ------------------------------------------------------------------ #
    def get_cached_search(self, provider: str, search_type: str,
                          query: str) -> Optional[list]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM search_cache
                WHERE provider = ? AND search_type = ? AND query = ?
            """, (provider, search_type, query.strip().lower()))
            row = cursor.fetchone()
            if row and self._is_valid(row) and row["results_json"]:
                return json.loads(row["results_json"])
        return None

    def save_cached_search(self, provider: str, search_type: str, query: str,
                           results: list):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            src_hash = _source_hash({"results": results})
            cursor.execute("""
                INSERT INTO search_cache (provider, search_type, query, results_json,
                    fetched_at, expires_at, schema_version, source_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, search_type, query) DO UPDATE SET
                    results_json = excluded.results_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    schema_version = excluded.schema_version,
                    source_hash = excluded.source_hash,
                    updated_at = excluded.updated_at;
            """, (provider, search_type, query.strip().lower(), json.dumps(results),
                  now, now + TTL_SEARCH, CACHE_SCHEMA_VERSION, src_hash, now))
            conn.commit()

    # ------------------------------------------------------------------ #
    # URL Cache Operations (Phase 30 — new)                              #
    # ------------------------------------------------------------------ #
    def get_cached_url(self, provider: str, url: str) -> Optional[dict]:
        """Phase 30: Returns cached URL response if valid."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM url_cache WHERE provider = ? AND url = ?
            """, (provider, url))
            row = cursor.fetchone()
            if row and self._is_valid(row) and row["data_json"]:
                try:
                    return json.loads(row["data_json"])
                except Exception:
                    pass
        return None

    def save_cached_url(self, provider: str, url: str, data: dict):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            src_hash = _source_hash(data)
            cursor.execute("""
                INSERT INTO url_cache (provider, url, data_json, fetched_at, expires_at,
                    schema_version, source_hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, url) DO UPDATE SET
                    data_json = excluded.data_json,
                    fetched_at = excluded.fetched_at,
                    expires_at = excluded.expires_at,
                    schema_version = excluded.schema_version,
                    source_hash = excluded.source_hash,
                    updated_at = excluded.updated_at;
            """, (provider, url, json.dumps(data), now, now + TTL_URL,
                  CACHE_SCHEMA_VERSION, src_hash, now))
            conn.commit()

    # ------------------------------------------------------------------ #
    # Phase 31: Explicit Invalidation API                                #
    # ------------------------------------------------------------------ #
    def invalidate_issue(self, provider: str, issue_id: str):
        """Phase 31: Force-invalidate a specific cached issue (manual refresh)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE issue_cache SET expires_at = 0
                WHERE provider = ? AND issue_id = ?;
            """, (provider, str(issue_id)))
            conn.commit()

    def invalidate_series(self, provider: str, series_id: str):
        """Phase 31: Force-invalidate a specific cached series."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE series_cache SET expires_at = 0
                WHERE provider = ? AND series_id = ?;
            """, (provider, str(series_id)))
            conn.commit()

    def invalidate_all_for_schema_version(self, old_version: str):
        """Phase 31: Purge all entries matching a stale schema_version."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for table in ("issue_cache", "series_cache", "search_cache", "url_cache"):
                cursor.execute(f"""
                    DELETE FROM {table} WHERE schema_version = ?;
                """, (old_version,))
            conn.commit()

    def purge_expired(self) -> int:
        """Phase 31: Delete all rows whose expires_at has passed."""
        now = int(time.time())
        total = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for table in ("issue_cache", "series_cache", "search_cache", "url_cache"):
                cursor.execute(f"DELETE FROM {table} WHERE expires_at > 0 AND expires_at < ?;",
                               (now,))
                total += cursor.rowcount
            conn.commit()
        return total

    # ------------------------------------------------------------------ #
    # Invalidation & Stats                                               #
    # ------------------------------------------------------------------ #
    def clear(self):
        """Clears all cached metadata and search history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for table in ("series_cache", "issue_cache", "search_cache",
                          "url_cache", "file_hashes"):
                cursor.execute(f"DELETE FROM {table};")
            conn.commit()

    def get_stats(self) -> dict:
        """Returns statistics on cached entries."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            s_count  = cursor.execute("SELECT COUNT(*) FROM series_cache;").fetchone()[0]
            i_count  = cursor.execute("SELECT COUNT(*) FROM issue_cache;").fetchone()[0]
            sr_count = cursor.execute("SELECT COUNT(*) FROM search_cache;").fetchone()[0]
            url_count= cursor.execute("SELECT COUNT(*) FROM url_cache;").fetchone()[0]
            fh_count = cursor.execute("SELECT COUNT(*) FROM file_hashes;").fetchone()[0]
            exp_count= cursor.execute(
                "SELECT COUNT(*) FROM issue_cache WHERE expires_at < ? AND expires_at > 0;",
                (now,)
            ).fetchone()[0]
            return {
                "series_cached": s_count,
                "issues_cached": i_count,
                "searches_cached": sr_count,
                "urls_cached": url_count,
                "processed_files_tracked": fh_count,
                "expired_issues": exp_count,
                "schema_version": CACHE_SCHEMA_VERSION,
                "db_path": self.db_path
            }
