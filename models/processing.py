import time
from dataclasses import dataclass

@dataclass
class ProcessingRecord:
    """
    Represents a durable processing job state record in the SQLite processing database.
    """
    job_id: str = ""
    archive_path: str = ""
    archive_sha256: str = ""
    status: str = "PENDING"              # PENDING, PROCESSING, SUCCESS, SKIPPED, REVIEW, UNRESOLVED, FAILED
    provider: str = ""
    provider_id: str = ""
    confidence: float = 0.0
    started_at: int = 0
    completed_at: int = 0
    attempts: int = 0
    error_code: str = ""
    error_message: str = ""
    generator_version: str = "2.0"

    def mark_started(self):
        self.status = "PROCESSING"
        self.started_at = int(time.time())
        self.attempts += 1

    def mark_success(self, provider: str = "", provider_id: str = "", confidence: float = 100.0):
        self.status = "SUCCESS"
        self.provider = provider
        self.provider_id = provider_id
        self.confidence = confidence
        self.completed_at = int(time.time())

    def mark_failed(self, error_message: str, error_code: str = "PROCESSING_ERROR"):
        self.status = "FAILED"
        self.error_message = error_message
        self.error_code = error_code
        self.completed_at = int(time.time())

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "archive_path": self.archive_path,
            "archive_sha256": self.archive_sha256,
            "status": self.status,
            "provider": self.provider,
            "provider_id": self.provider_id,
            "confidence": self.confidence,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "attempts": self.attempts,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "generator_version": self.generator_version
        }
