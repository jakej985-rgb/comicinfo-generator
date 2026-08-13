import os
import sqlite3
import time
import uuid
from typing import Optional, List, Dict, Any

STATUS_PENDING = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_SUCCESS = "SUCCESS"
STATUS_SKIPPED = "SKIPPED"
STATUS_REVIEW = "REVIEW"
STATUS_UNRESOLVED = "UNRESOLVED"
STATUS_FAILED = "FAILED"

class JobStore:
    """
    Phase 20 & 21: Durable Processing Job Store backed by SQLite.
    Survives restarts, crashes, and power failures without losing work.
    """

    def __init__(self, db_path: str = "~/.comicinfo/jobs.db"):
        self.db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self.reset_stale_processing_jobs()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes processing_jobs table schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processing_jobs (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    sha256 TEXT,
                    size INTEGER,
                    mtime INTEGER,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    attempts INTEGER DEFAULT 0,
                    provider TEXT,
                    provider_id TEXT,
                    confidence REAL,
                    created_at INTEGER,
                    started_at INTEGER,
                    completed_at INTEGER,
                    error_code TEXT,
                    error_message TEXT,
                    generator_version TEXT DEFAULT '2.0'
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON processing_jobs(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_path ON processing_jobs(path);")
            conn.commit()

    def reset_stale_processing_jobs(self) -> int:
        """
        Phase 21: Make Queue Restart-Safe.
        Resets any jobs left in 'PROCESSING' state during a crash or restart back to 'PENDING'.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE processing_jobs
                SET status = 'PENDING', started_at = NULL
                WHERE status = 'PROCESSING';
            """)
            count = cursor.rowcount
            conn.commit()
            return count

    def create_job(self, file_path: str) -> dict:
        """Creates or retrieves an existing pending/processing job for a file path."""
        abs_path = os.path.abspath(file_path)
        size = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0
        mtime = int(os.path.getmtime(abs_path)) if os.path.exists(abs_path) else 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check existing pending/processing job
            cursor.execute("""
                SELECT * FROM processing_jobs
                WHERE path = ? AND status IN ('PENDING', 'PROCESSING');
            """, (abs_path,))
            existing = cursor.fetchone()
            if existing:
                return dict(existing)

            job_id = str(uuid.uuid4())
            now = int(time.time())

            cursor.execute("""
                INSERT INTO processing_jobs (id, path, size, mtime, status, created_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?);
            """, (job_id, abs_path, size, mtime, now))
            conn.commit()

            cursor.execute("SELECT * FROM processing_jobs WHERE id = ?;", (job_id,))
            return dict(cursor.fetchone())

    def get_job(self, job_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM processing_jobs WHERE id = ?;", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetch_next_pending_job(self) -> Optional[dict]:
        """Atomically fetches the next PENDING job and marks it as PROCESSING."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM processing_jobs
                WHERE status = 'PENDING'
                ORDER BY created_at ASC
                LIMIT 1;
            """)
            row = cursor.fetchone()
            if not row:
                return None

            job = dict(row)
            now = int(time.time())
            cursor.execute("""
                UPDATE processing_jobs
                SET status = 'PROCESSING', started_at = ?, attempts = attempts + 1
                WHERE id = ?;
            """, (now, job["id"]))
            conn.commit()
            job["status"] = STATUS_PROCESSING
            job["started_at"] = now
            job["attempts"] += 1
            return job

    def update_job_status(
        self,
        job_id: str,
        status: str,
        provider: str = "",
        provider_id: str = "",
        confidence: float = 0.0,
        error_code: str = "",
        error_message: str = "",
        sha256: str = ""
    ):
        """Updates status and completion fields for a job."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            cursor.execute("""
                UPDATE processing_jobs
                SET status = ?, provider = ?, provider_id = ?, confidence = ?,
                    error_code = ?, error_message = ?, sha256 = ?, completed_at = ?
                WHERE id = ?;
            """, (status, provider, provider_id, confidence, error_code, error_message, sha256, now, job_id))
            conn.commit()

    def list_jobs(self, status: Optional[str] = None, limit: int = 100) -> List[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if status:
                cursor.execute("""
                    SELECT * FROM processing_jobs
                    WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?;
                """, (status, limit))
            else:
                cursor.execute("""
                    SELECT * FROM processing_jobs
                    ORDER BY created_at DESC
                    LIMIT ?;
                """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
