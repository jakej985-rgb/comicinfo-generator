"""
observability/logging.py — Phase 33

Structured job event logger.
Each processing event emits a structured log line with consistent key=value fields.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Dict

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


def sanitize_log_text(text: str) -> str:
    """Masks API keys, tokens, passwords, and secret strings from logs."""
    import re
    # Match common key patterns: api_key=..., apikey=..., token=..., key=...
    sanitized = re.sub(r'(?i)(api[_-]?key|token|auth|password|secret)\s*[:=]\s*([^\s,;&"\']+)', r'\1=***', text)
    # Match 32+ hex/alphanumeric tokens in query params e.g. api_key=a1b2c3d4...
    sanitized = re.sub(r'([?&]api_key=)[a-zA-Z0-9_\-]+', r'\1***', sanitized)
    return sanitized


@dataclass
class ProductionJobLog:
    """
    Phase 92: Production Observability structured job log representation.
    """
    filename: str = ""
    series: str = ""
    issue: str = ""
    year: Optional[int] = None
    provider: str = ""
    fallback: bool = False
    confidence: Optional[float] = None
    provider_results: Dict[str, str] = field(default_factory=dict)
    retryable: Optional[bool] = None
    action: str = "UPDATE ComicInfo.xml"
    archive_verified: Optional[bool] = None
    result: str = "COMPLETED"
    error_message: str = ""

    def format(self) -> str:
        """Formats into the Phase 92 structured multi-section log format."""
        sections = []

        # JOB START
        sections.append("JOB START\n" + f"file={os.path.basename(self.filename) if self.filename else ''}")

        # IDENTITY
        identity_lines = ["IDENTITY"]
        if self.series:
            identity_lines.append(f"series={self.series}")
        if self.issue:
            identity_lines.append(f"issue={self.issue}")
        if self.year:
            identity_lines.append(f"year={self.year}")
        if len(identity_lines) > 1:
            sections.append("\n".join(identity_lines))

        # RESOLUTION
        res_lines = ["RESOLUTION"]
        if self.provider_results:
            for prov, res in self.provider_results.items():
                res_lines.append(f"{prov}={res}")
            res_lines.append(f"fallback={'true' if self.fallback else 'false'}")
        else:
            if self.provider:
                res_lines.append(f"provider={self.provider}")
            if self.fallback:
                res_lines.append("fallback=true")
            elif self.provider:
                res_lines.append("fallback=false")
            if self.confidence is not None:
                res_lines.append(f"confidence={int(self.confidence)}")

        if self.retryable is not None:
            res_lines.append(f"retryable={'true' if self.retryable else 'false'}")

        if len(res_lines) > 1:
            sections.append("\n".join(res_lines))

        # ACTION
        if self.action:
            sections.append(f"ACTION\n{self.action}")

        # WRITE
        if self.archive_verified is not None:
            sections.append(f"WRITE\narchive verified={'true' if self.archive_verified else 'false'}")

        # RESULT
        result_str = f"RESULT\n{self.result}"
        if self.error_message:
            result_str += f"\nerror={self.error_message}"
        sections.append(result_str)

        raw_output = "\n\n".join(sections)
        return sanitize_log_text(raw_output)


def log_production_job(job_log: ProductionJobLog):
    """Emits a Phase 92 production structured job log."""
    formatted = job_log.format()
    level = logging.INFO if job_log.result in ("COMPLETED", "SUCCESS", "SKIPPED") else logging.WARNING
    _logger.log(level, f"\n{formatted}\n")
    return formatted


def log_provider_call(provider: str, url: str, duration_ms: float, status_code: int = 0):
    sanitized_url = sanitize_log_text(url)
    _logger.debug(
        f"PROVIDER_CALL provider={provider} "
        f"url={sanitized_url[:80]}… "
        f"duration={duration_ms:.0f}ms "
        f"status={status_code}"
    )
