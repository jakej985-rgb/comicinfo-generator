import os
import sqlite3
import time
import uuid
from typing import Optional, List, Dict, Any

STATUS_DISCOVERED = "DISCOVERED"
STATUS_QUEUED = "QUEUED"
STATUS_PROCESSING = "PROCESSING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED = "FAILED"
STATUS_RETRYING = "RETRYING"
STATUS_REVIEW = "REVIEW"

# Backward compatibility aliases
STATUS_PENDING = "PENDING"
STATUS_SUCCESS = "SUCCESS"
STATUS_SKIPPED = "SKIPPED"
STATUS_UNRESOLVED = "UNRESOLVED"

ACTIVE_CLAIMABLE_STATUSES = (STATUS_QUEUED, STATUS_PENDING, STATUS_DISCOVERED, STATUS_RETRYING)

class JobStore:
    """
    Phase 20 & 21 & Phase 85: Durable Processing Job Store backed by SQLite.
    Authoritative source of processing state (DISCOVERED, QUEUED, PROCESSING, COMPLETED, FAILED, RETRYING, REVIEW).
    Survives restarts, crashes, and power failures without losing work.
    """

    def __init__(self, db_path: str = "~/.comicinfo/jobs.db"):
        self.db_path = os.path.expanduser(db_path)
        if self.db_path != ":memory:" and os.path.dirname(self.db_path):
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self.reset_stale_processing_jobs()

    def _get_connection(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if not hasattr(self, "_mem_conn") or self._mem_conn is None:
                self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._mem_conn.row_factory = sqlite3.Row
            return self._mem_conn
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
        except Exception:
            pass
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
                    max_attempts INTEGER DEFAULT 3,
                    worker_id TEXT,
                    claimed_at INTEGER,
                    lease_until INTEGER,
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_lease ON processing_jobs(status, lease_until);")
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
                SET status = 'PENDING', started_at = NULL, worker_id = NULL, lease_until = NULL
                WHERE status = 'PROCESSING';
            """)
            count = cursor.rowcount
            conn.commit()
            return count

    def create_job(self, file_path: str, initial_status: str = STATUS_PENDING) -> dict:
        """
        Phase 22 & Phase 85: Deduplicates jobs using path + SHA256 as primary identity.
        If same path and same SHA256 is already active (DISCOVERED, QUEUED, PENDING, PROCESSING, RETRYING),
        returns existing job.
        If SHA256 changes (modified file), creates a new processing job.
        """
        abs_path = os.path.abspath(file_path)
        size = os.path.getsize(abs_path) if os.path.exists(abs_path) else 0
        mtime = int(os.path.getmtime(abs_path)) if os.path.exists(abs_path) else 0
        
        sha256 = ""
        if os.path.exists(abs_path):
            try:
                import hashlib
                h = hashlib.sha256()
                buf = bytearray(262144)
                mv = memoryview(buf)
                with open(abs_path, "rb", buffering=0) as f:
                    while True:
                        n = f.readinto(mv)
                        if not n:
                            break
                        h.update(mv[:n])
                sha256 = h.hexdigest()
            except Exception:
                pass

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Phase 22 & 85 Deduplication check (same path + same SHA256 across active states)
            if sha256:
                cursor.execute("""
                    SELECT * FROM processing_jobs
                    WHERE path = ? AND sha256 = ? AND status IN ('DISCOVERED', 'QUEUED', 'PENDING', 'PROCESSING', 'RETRYING');
                """, (abs_path, sha256))
            else:
                cursor.execute("""
                    SELECT * FROM processing_jobs
                    WHERE path = ? AND status IN ('DISCOVERED', 'QUEUED', 'PENDING', 'PROCESSING', 'RETRYING');
                """, (abs_path,))

            existing = cursor.fetchone()
            if existing:
                return dict(existing)

            job_id = str(uuid.uuid4())
            now = int(time.time())

            cursor.execute("""
                INSERT INTO processing_jobs (id, path, sha256, size, mtime, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (job_id, abs_path, sha256, size, mtime, initial_status, now))
            conn.commit()

            cursor.execute("SELECT * FROM processing_jobs WHERE id = ?;", (job_id,))
            return dict(cursor.fetchone())


    def get_job(self, job_id: str) -> Optional[dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM processing_jobs WHERE id = ?;", (job_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def claim_job(self, worker_id: str = "default_worker", lease_seconds: float = 300.0, max_attempts: int = 3) -> Optional[dict]:
        """
        Phase 48 & Phase 85: Atomically claims the next eligible job for a specific worker.
        Uses SQLite exclusive transaction semantics (BEGIN IMMEDIATE) to guarantee
        that two concurrent workers cannot claim the same job.
        Eligible jobs:
        - status IN ('DISCOVERED', 'QUEUED', 'PENDING', 'RETRYING') and attempts < max_attempts
        - status == 'PROCESSING' and lease_until < now and attempts < max_attempts (expired lease recovery)
        """
        now = time.time()
        lease_until = now + lease_seconds

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE;")

            # 1. Fail expired leases where attempts >= max_attempts
            cursor.execute("""
                UPDATE processing_jobs
                SET status = 'FAILED', error_code = 'MAX_ATTEMPTS_EXCEEDED', error_message = 'Job exceeded maximum retry attempts'
                WHERE status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < ? AND attempts >= ?;
            """, (now, max_attempts))

            # 2. Reclaim expired leases where attempts < max_attempts back to RETRYING / PENDING
            cursor.execute("""
                UPDATE processing_jobs
                SET status = 'RETRYING', worker_id = NULL, lease_until = NULL
                WHERE status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < ? AND attempts < ?;
            """, (now, max_attempts))

            # 3. Find next available eligible job
            cursor.execute("""
                SELECT id FROM processing_jobs
                WHERE status IN ('DISCOVERED', 'QUEUED', 'PENDING', 'RETRYING') AND attempts < ?
                ORDER BY created_at ASC
                LIMIT 1;
            """, (max_attempts,))
            row = cursor.fetchone()

            if not row:
                conn.commit()
                return None

            job_id = row["id"]
            cursor.execute("""
                UPDATE processing_jobs
                SET status = 'PROCESSING',
                    worker_id = ?,
                    claimed_at = ?,
                    started_at = ?,
                    lease_until = ?,
                    attempts = attempts + 1
                WHERE id = ? AND status IN ('DISCOVERED', 'QUEUED', 'PENDING', 'RETRYING');
            """, (worker_id, int(now), int(now), lease_until, job_id))

            if cursor.rowcount > 0:
                cursor.execute("SELECT * FROM processing_jobs WHERE id = ?;", (job_id,))
                claimed_job = dict(cursor.fetchone())
                conn.commit()
                return claimed_job

            conn.commit()
            return None

    def mark_discovered(self, file_path: str) -> dict:
        """Phase 85: Records a file as DISCOVERED before queueing."""
        return self.create_job(file_path, initial_status=STATUS_DISCOVERED)

    def mark_queued(self, job_id: str):
        """Phase 85: Transitions job to QUEUED state."""
        self.update_job_status(job_id, status=STATUS_QUEUED)

    def mark_completed(
        self,
        job_id: str,
        provider: str = "",
        provider_id: str = "",
        confidence: float = 0.0,
        sha256: str = ""
    ):
        """Phase 85: Transitions job to COMPLETED state upon successful embed and hash tracking."""
        self.update_job_status(
            job_id=job_id,
            status=STATUS_COMPLETED,
            provider=provider,
            provider_id=provider_id,
            confidence=confidence,
            sha256=sha256
        )

    def mark_failed(self, job_id: str, error_code: str = "", error_message: str = ""):
        """Phase 85: Transitions job to FAILED state."""
        self.update_job_status(
            job_id=job_id,
            status=STATUS_FAILED,
            error_code=error_code,
            error_message=error_message
        )

    def mark_retrying(self, job_id: str, error_code: str = "", error_message: str = ""):
        """Phase 85: Transitions job to RETRYING state."""
        self.update_job_status(
            job_id=job_id,
            status=STATUS_RETRYING,
            error_code=error_code,
            error_message=error_message
        )

    def mark_review(self, job_id: str, confidence: float = 0.0, error_message: str = ""):
        """Phase 85: Transitions job to REVIEW state."""
        self.update_job_status(
            job_id=job_id,
            status=STATUS_REVIEW,
            confidence=confidence,
            error_message=error_message
        )

    def renew_lease(self, job_id: str, worker_id: str, lease_seconds: float = 300.0) -> bool:
        """
        Phase 48: Renews the active lease for a job currently claimed by worker_id.
        """
        now = time.time()
        lease_until = now + lease_seconds
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE processing_jobs
                SET lease_until = ?
                WHERE id = ? AND worker_id = ? AND status = 'PROCESSING';
            """, (lease_until, job_id, worker_id))
            conn.commit()
            return cursor.rowcount > 0

    def reclaim_expired_leases(self, max_attempts: int = 3) -> int:
        """
        Phase 48: Reclaims expired leases, resetting recoverables to PENDING and failing poison pills.
        """
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE processing_jobs
                SET status = 'PENDING', worker_id = NULL, lease_until = NULL
                WHERE status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < ? AND attempts < ?;
            """, (now, max_attempts))
            reclaimed = cursor.rowcount

            cursor.execute("""
                UPDATE processing_jobs
                SET status = 'FAILED', error_code = 'MAX_ATTEMPTS_EXCEEDED', error_message = 'Job exceeded maximum retry attempts'
                WHERE status = 'PROCESSING' AND lease_until IS NOT NULL AND lease_until < ? AND attempts >= ?;
            """, (now, max_attempts))
            conn.commit()
            return reclaimed

    def fetch_next_pending_job(self, worker_id: str = "default_worker") -> Optional[dict]:
        """Atomically fetches the next PENDING job and marks it as PROCESSING for worker_id."""
        return self.claim_job(worker_id=worker_id)

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
