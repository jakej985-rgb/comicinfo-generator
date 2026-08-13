import os
import json
import sqlite3
import time
from typing import Optional, Dict, List
from models.comic import Comic

class CacheManager:
    """
    SQLite Cache Manager.
    Stores cached series, issue metadata, search results, and file hash tracking information.
    """

    def __init__(self, db_path: str = "~/.comicinfo/cache.db"):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes database schema if tables do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Series Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS series_cache (
                    provider TEXT NOT NULL,
                    series_id TEXT NOT NULL,
                    name TEXT,
                    year INTEGER,
                    publisher TEXT,
                    data_json TEXT,
                    updated_at INTEGER,
                    PRIMARY KEY (provider, series_id)
                );
            """)

            # Issue Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS issue_cache (
                    provider TEXT NOT NULL,
                    issue_id TEXT NOT NULL,
                    series_id TEXT,
                    number TEXT,
                    title TEXT,
                    data_json TEXT,
                    updated_at INTEGER,
                    PRIMARY KEY (provider, issue_id)
                );
            """)

            # Search History Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS search_cache (
                    provider TEXT NOT NULL,
                    search_type TEXT NOT NULL,
                    query TEXT NOT NULL,
                    results_json TEXT,
                    updated_at INTEGER,
                    PRIMARY KEY (provider, search_type, query)
                );
            """)

            # File Hash Tracking Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS file_hashes (
                    file_path TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    mtime INTEGER NOT NULL,
                    provider_used TEXT,
                    metadata_version TEXT,
                    processed_at INTEGER
                );
            """)

            conn.commit()

    # --- File Hash Operations ---
    def get_file_record(self, file_path: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM file_hashes WHERE file_path = ?", (os.path.abspath(file_path),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_file_record(self, file_path: str, sha256: str, file_size: int, mtime: int, provider_used: str = "", metadata_version: str = "2.0"):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            cursor.execute("""
                INSERT INTO file_hashes (file_path, sha256, file_size, mtime, provider_used, metadata_version, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    sha256 = excluded.sha256,
                    file_size = excluded.file_size,
                    mtime = excluded.mtime,
                    provider_used = excluded.provider_used,
                    metadata_version = excluded.metadata_version,
                    processed_at = excluded.processed_at;
            """, (os.path.abspath(file_path), sha256, file_size, mtime, provider_used, metadata_version, now))
            conn.commit()

    # --- Issue Cache Operations ---
    def get_cached_issue(self, provider: str, issue_id: str) -> Optional[Comic]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_json FROM issue_cache WHERE provider = ? AND issue_id = ?", (provider, str(issue_id)))
            row = cursor.fetchone()
            if row and row["data_json"]:
                try:
                    data = json.loads(row["data_json"])
                    c = Comic(**data)
                    return c
                except Exception:
                    pass
        return None

    def save_cached_issue(self, provider: str, issue_id: str, comic: Comic, series_id: str = ""):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            # Convert Comic object to dict
            data_dict = {
                "title": comic.title, "series": comic.series, "number": comic.number,
                "volume": comic.volume, "count": comic.count, "summary": comic.summary,
                "notes": comic.notes, "year": comic.year, "month": comic.month, "day": comic.day,
                "publisher": comic.publisher, "genre": comic.genre, "web": comic.web,
                "language": comic.language, "format": comic.format, "writers": comic.writers,
                "pencillers": comic.pencillers, "inkers": comic.inkers, "colorists": comic.colorists,
                "letterers": comic.letterers, "cover_artists": comic.cover_artists,
                "characters": comic.characters, "teams": comic.teams, "story_arcs": comic.story_arcs,
                "provider_name": provider, "provider_id": str(issue_id)
            }
            cursor.execute("""
                INSERT INTO issue_cache (provider, issue_id, series_id, number, title, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, issue_id) DO UPDATE SET
                    series_id = excluded.series_id,
                    number = excluded.number,
                    title = excluded.title,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at;
            """, (provider, str(issue_id), series_id, comic.number, comic.title, json.dumps(data_dict), now))
            conn.commit()

    # --- Series Cache Operations ---
    def get_cached_series(self, provider: str, series_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data_json, updated_at FROM series_cache
                WHERE provider = ? AND series_id = ?
            """, (provider, str(series_id)))
            row = cursor.fetchone()
            if row and row["data_json"]:
                # Invalidate series volume cache if older than 7 days (604800s)
                if int(time.time()) - row["updated_at"] < 604800:
                    try:
                        return json.loads(row["data_json"])
                    except Exception:
                        pass
        return None

    def save_cached_series(self, provider: str, series_id: str, name: str = "", year: int = 0, publisher: str = "", data: dict = None):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            data_json = json.dumps(data or {})
            cursor.execute("""
                INSERT INTO series_cache (provider, series_id, name, year, publisher, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, series_id) DO UPDATE SET
                    name = excluded.name,
                    year = excluded.year,
                    publisher = excluded.publisher,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at;
            """, (provider, str(series_id), name, year, publisher, data_json, now))
            conn.commit()

    # --- Search Cache Operations ---
    def get_cached_search(self, provider: str, search_type: str, query: str) -> Optional[list[dict]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT results_json, updated_at FROM search_cache
                WHERE provider = ? AND search_type = ? AND query = ?
            """, (provider, search_type, query.strip().lower()))
            row = cursor.fetchone()
            if row and row["results_json"]:
                # Invalidate if older than 24 hours
                if int(time.time()) - row["updated_at"] < 86400:
                    return json.loads(row["results_json"])
        return None

    def save_cached_search(self, provider: str, search_type: str, query: str, results: list[dict]):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            cursor.execute("""
                INSERT INTO search_cache (provider, search_type, query, results_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, search_type, query) DO UPDATE SET
                    results_json = excluded.results_json,
                    updated_at = excluded.updated_at;
            """, (provider, search_type, query.strip().lower(), json.dumps(results), now))
            conn.commit()

    # --- Invalidation & Stats ---
    def clear(self):
        """Clears all cached metadata and search history."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM series_cache;")
            cursor.execute("DELETE FROM issue_cache;")
            cursor.execute("DELETE FROM search_cache;")
            cursor.execute("DELETE FROM file_hashes;")
            conn.commit()

    def get_stats(self) -> dict:
        """Returns statistics on cached entries."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            s_count = cursor.execute("SELECT COUNT(*) FROM series_cache;").fetchone()[0]
            i_count = cursor.execute("SELECT COUNT(*) FROM issue_cache;").fetchone()[0]
            sr_count = cursor.execute("SELECT COUNT(*) FROM search_cache;").fetchone()[0]
            fh_count = cursor.execute("SELECT COUNT(*) FROM file_hashes;").fetchone()[0]
            return {
                "series_cached": s_count,
                "issues_cached": i_count,
                "searches_cached": sr_count,
                "processed_files_tracked": fh_count,
                "db_path": self.db_path
            }
