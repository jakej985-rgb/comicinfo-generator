"""
observability/metrics.py — Phase 34

Thread-safe in-memory metrics counters and timing histograms.
Tracks the counters required by plan.md Phase 34.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class ProviderMetrics:
    """Per-provider timing and failure tracking."""
    name: str
    call_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def avg_response_ms(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    @property
    def cache_hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total


class MetricsCollector:
    """
    Phase 34: Thread-safe counters for the full processing pipeline.
    Counters:
      - files_processed
      - files_skipped
      - files_resolved       (SUCCESS)
      - files_unresolved     (UNRESOLVED)
      - manual_reviews       (REVIEW / MANUAL_REVIEW)
      - provider_failures
      - archive_failures
      - total_processing_ms  (for average calculation)
      - per-provider metrics
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.files_processed: int = 0
        self.files_skipped: int = 0
        self.files_resolved: int = 0
        self.files_unresolved: int = 0
        self.manual_reviews: int = 0
        self.provider_failures: int = 0
        self.archive_failures: int = 0
        self._processing_durations_ms: List[float] = []
        self._providers: Dict[str, ProviderMetrics] = {}
        self._started_at: float = time.time()

    def _provider(self, name: str) -> ProviderMetrics:
        if name not in self._providers:
            self._providers[name] = ProviderMetrics(name=name)
        return self._providers[name]

    # ------------------------------------------------------------------ #
    # Job-level recording                                                 #
    # ------------------------------------------------------------------ #
    def record_job_result(self, status: str, duration_ms: float = 0.0):
        """Record the outcome of a single processing job."""
        with self._lock:
            self.files_processed += 1
            self._processing_durations_ms.append(duration_ms)
            if status == "SUCCESS":
                self.files_resolved += 1
            elif status == "SKIPPED":
                self.files_skipped += 1
            elif status in ("UNRESOLVED", "FAILED"):
                self.files_unresolved += 1
            elif status in ("REVIEW", "MANUAL_REVIEW"):
                self.manual_reviews += 1

    def record_archive_failure(self):
        with self._lock:
            self.archive_failures += 1

    # ------------------------------------------------------------------ #
    # Provider-level recording                                            #
    # ------------------------------------------------------------------ #
    def record_provider_call(
        self, provider: str, duration_ms: float, success: bool = True
    ):
        with self._lock:
            p = self._provider(provider)
            p.call_count += 1
            p.total_duration_ms += duration_ms
            if not success:
                p.failure_count += 1
                self.provider_failures += 1

    def record_cache_hit(self, provider: str):
        with self._lock:
            self._provider(provider).cache_hits += 1

    def record_cache_miss(self, provider: str):
        with self._lock:
            self._provider(provider).cache_misses += 1

    # ------------------------------------------------------------------ #
    # Snapshots                                                           #
    # ------------------------------------------------------------------ #
    @property
    def avg_processing_ms(self) -> float:
        with self._lock:
            if not self._processing_durations_ms:
                return 0.0
            return sum(self._processing_durations_ms) / len(self._processing_durations_ms)

    def snapshot(self) -> dict:
        """Returns a point-in-time snapshot of all metrics."""
        with self._lock:
            provider_data = {}
            for name, p in self._providers.items():
                provider_data[name] = {
                    "call_count": p.call_count,
                    "failure_count": p.failure_count,
                    "avg_response_ms": round(p.avg_response_ms, 1),
                    "cache_hit_rate": round(p.cache_hit_rate * 100, 1),
                }
            total_runs = len(self._processing_durations_ms)
            avg_ms = (sum(self._processing_durations_ms) / total_runs
                      if total_runs else 0.0)
            return {
                "files_processed": self.files_processed,
                "files_skipped": self.files_skipped,
                "files_resolved": self.files_resolved,
                "files_unresolved": self.files_unresolved,
                "manual_reviews": self.manual_reviews,
                "provider_failures": self.provider_failures,
                "archive_failures": self.archive_failures,
                "avg_processing_ms": round(avg_ms, 1),
                "uptime_seconds": round(time.time() - self._started_at, 1),
                "providers": provider_data,
            }

    def reset(self):
        """Resets all counters (useful for testing)."""
        with self._lock:
            self.files_processed = 0
            self.files_skipped = 0
            self.files_resolved = 0
            self.files_unresolved = 0
            self.manual_reviews = 0
            self.provider_failures = 0
            self.archive_failures = 0
            self._processing_durations_ms.clear()
            self._providers.clear()
            self._started_at = time.time()


# Global singleton — import and use directly
metrics = MetricsCollector()
