"""
observability/logging.py — Phase 33

Structured job event logger.
Each processing event emits a structured log line with consistent key=value fields.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

# Root logger for the application
_logger = logging.getLogger("comicinfo")


def configure_logging(level: str = "INFO", log_file: Optional[str] = None):
    """Call once at startup to configure the root logger."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True
    )


@dataclass
class JobEvent:
    """
    Phase 33: Structured data for a single archive processing job event.
    All fields that are logged when processing begins or completes.
    """
    job_id: str = ""
    archive: str = ""
    sha256: str = ""
    provider: str = ""
    provider_id: str = ""
    confidence: float = 0.0
    status: str = ""           # SUCCESS / SKIPPED / REVIEW / UNRESOLVED / FAILED
    duration_ms: float = 0.0
    error_code: str = ""
    error_message: str = ""

    def to_kv(self) -> str:
        """Formats the event as a key=value string for human-readable logs."""
        parts = [f"job={self.job_id}"]
        if self.archive:
            parts.append(f"archive={self.archive}")
        if self.sha256:
            parts.append(f"sha256={self.sha256[:12]}…")
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.provider_id:
            parts.append(f"issue={self.provider_id}")
        if self.confidence:
            parts.append(f"confidence={self.confidence:.0f}")
        if self.status:
            parts.append(f"status={self.status}")
        if self.duration_ms:
            parts.append(f"duration={self.duration_ms:.0f}ms")
        if self.error_code:
            parts.append(f"error_code={self.error_code}")
        if self.error_message:
            parts.append(f"error={self.error_message!r}")
        return " ".join(parts)

    def to_json(self) -> str:
        return json.dumps({
            "job_id": self.job_id,
            "archive": self.archive,
            "sha256": self.sha256,
            "provider": self.provider,
            "provider_id": self.provider_id,
            "confidence": self.confidence,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
        })


def log_job_start(job_id: str, archive: str, sha256: str = ""):
    event = JobEvent(job_id=job_id, archive=archive, sha256=sha256, status="PROCESSING")
    _logger.info("JOB_START " + event.to_kv())


def log_job_complete(
    job_id: str,
    archive: str,
    status: str,
    provider: str = "",
    provider_id: str = "",
    confidence: float = 0.0,
    duration_ms: float = 0.0,
    sha256: str = "",
    error_code: str = "",
    error_message: str = ""
):
    event = JobEvent(
        job_id=job_id, archive=archive, sha256=sha256,
        provider=provider, provider_id=provider_id,
        confidence=confidence, status=status,
        duration_ms=duration_ms,
        error_code=error_code, error_message=error_message
    )
    level = logging.INFO if status in ("SUCCESS", "SKIPPED") else logging.WARNING
    _logger.log(level, "JOB_DONE  " + event.to_kv())
    return event


def log_provider_call(provider: str, url: str, duration_ms: float, status_code: int = 0):
    _logger.debug(
        f"PROVIDER_CALL provider={provider} "
        f"url={url[:80]}… "
        f"duration={duration_ms:.0f}ms "
        f"status={status_code}"
    )
