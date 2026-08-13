"""
observability/rate_limiter.py — Phase 35

Per-provider token-bucket rate limiter.
Workers can run concurrently, but external provider HTTP requests
are serialised through per-provider rate limiters to respect provider limits.

Default limits (conservative, can be overridden via config):
  ComicVine : 200 req / 15 minutes  → ~0.22 req/s
  GCD       : 60  req / minute      → 1.0  req/s
  Kapowarr  : unlimited (local)     → no limit

The token bucket refills continuously. If no token is available,
the calling thread sleeps until one becomes available.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class _TokenBucket:
    """Simple token-bucket rate limiter."""
    rate: float            # tokens refilled per second
    capacity: float        # max tokens (== burst capacity)
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self):
        self._tokens = self.capacity
        self._last_refill = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def acquire(self, timeout: float = 60.0) -> bool:
        """
        Blocks until a token is available or timeout expires.
        Returns True if acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait = (1.0 - self._tokens) / self.rate
            # Wait outside the lock
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(min(wait, 0.1))


class RateLimiterRegistry:
    """
    Phase 35: Registry of per-provider rate limiters.
    Providers not in the registry are treated as unlimited.
    """

    # Default provider configurations: (rate_per_second, burst_capacity)
    _DEFAULTS: Dict[str, tuple] = {
        "ComicVine": (200 / 900, 10),    # 200 req / 15 min, burst 10
        "CV":        (200 / 900, 10),
        "GCD":       (1.0,       5),     # 60 req / min, burst 5
        "GCP":       (1.0,       5),
        # Kapowarr is local — no limit applied
    }

    def __init__(self):
        self._limiters: Dict[str, Optional[_TokenBucket]] = {}
        self._lock = threading.Lock()

    def configure(self, provider: str, rate_per_second: float, burst: int = 5):
        """Registers or replaces a rate limiter for a specific provider."""
        with self._lock:
            self._limiters[provider] = _TokenBucket(rate=rate_per_second, capacity=float(burst))

    def _get_limiter(self, provider: str) -> Optional[_TokenBucket]:
        with self._lock:
            if provider not in self._limiters:
                if provider in self._DEFAULTS:
                    rate, burst = self._DEFAULTS[provider]
                    self._limiters[provider] = _TokenBucket(rate=rate, capacity=float(burst))
                else:
                    self._limiters[provider] = None  # unlimited
            return self._limiters[provider]

    def acquire(self, provider: str, timeout: float = 60.0) -> bool:
        """
        Acquires a rate-limit token for the given provider.
        Blocks until available or timeout expires.
        Returns True if acquired (or provider is unlimited), False on timeout.
        """
        limiter = self._get_limiter(provider)
        if limiter is None:
            return True  # unlimited provider
        return limiter.acquire(timeout=timeout)

    def remove(self, provider: str):
        """Removes the rate limiter for a provider (makes it unlimited)."""
        with self._lock:
            self._limiters.pop(provider, None)


# Global singleton
rate_limiter = RateLimiterRegistry()
