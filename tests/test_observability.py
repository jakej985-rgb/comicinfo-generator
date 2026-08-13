"""
Tests for Phase 33 (structured logging), Phase 34 (metrics),
Phase 35 (rate limiter), and Phase 36 (retry policy).
"""
import threading
import time
import unittest
import urllib.error

from observability.logging import JobEvent, log_job_complete, log_job_start
from observability.metrics import MetricsCollector
from observability.rate_limiter import RateLimiterRegistry
from observability.retry import (
    NonRetryableError, RetryableError, classify_http_error,
    is_retryable_exception, with_retry,
)


# ===================================================================== #
# Phase 33 — Structured Logging                                         #
# ===================================================================== #
class TestStructuredLogging(unittest.TestCase):

    def test_job_event_kv_contains_required_fields(self):
        e = JobEvent(
            job_id="1234",
            archive="Batman_001.cbz",
            sha256="abc123",
            provider="ComicVine",
            provider_id="4000-123456",
            confidence=97.0,
            status="SUCCESS",
            duration_ms=450.0
        )
        kv = e.to_kv()
        self.assertIn("job=1234", kv)
        self.assertIn("archive=Batman_001.cbz", kv)
        self.assertIn("provider=ComicVine", kv)
        self.assertIn("issue=4000-123456", kv)
        self.assertIn("confidence=97", kv)
        self.assertIn("status=SUCCESS", kv)
        self.assertIn("duration=450ms", kv)

    def test_job_event_json_roundtrip(self):
        import json
        e = JobEvent(
            job_id="9999", archive="X-Men_001.cbz", provider="GCD",
            provider_id="gcd-555", confidence=85.0, status="SUCCESS", duration_ms=200.0
        )
        data = json.loads(e.to_json())
        self.assertEqual(data["job_id"], "9999")
        self.assertEqual(data["provider"], "GCD")
        self.assertEqual(data["confidence"], 85.0)
        self.assertEqual(data["status"], "SUCCESS")

    def test_log_job_complete_returns_event(self):
        event = log_job_complete(
            job_id="5", archive="test.cbz", status="SUCCESS",
            provider="ComicVine", confidence=90.0, duration_ms=300.0
        )
        self.assertIsInstance(event, JobEvent)
        self.assertEqual(event.status, "SUCCESS")


# ===================================================================== #
# Phase 34 — Metrics                                                    #
# ===================================================================== #
class TestMetrics(unittest.TestCase):

    def setUp(self):
        self.m = MetricsCollector()

    def test_records_success(self):
        self.m.record_job_result("SUCCESS", duration_ms=500.0)
        snap = self.m.snapshot()
        self.assertEqual(snap["files_processed"], 1)
        self.assertEqual(snap["files_resolved"], 1)
        self.assertEqual(snap["files_skipped"], 0)

    def test_records_skipped(self):
        self.m.record_job_result("SKIPPED")
        snap = self.m.snapshot()
        self.assertEqual(snap["files_skipped"], 1)
        self.assertEqual(snap["files_processed"], 1)

    def test_records_manual_review(self):
        self.m.record_job_result("MANUAL_REVIEW")
        snap = self.m.snapshot()
        self.assertEqual(snap["manual_reviews"], 1)

    def test_records_unresolved(self):
        self.m.record_job_result("UNRESOLVED")
        snap = self.m.snapshot()
        self.assertEqual(snap["files_unresolved"], 1)

    def test_avg_processing_ms(self):
        self.m.record_job_result("SUCCESS", 100.0)
        self.m.record_job_result("SUCCESS", 300.0)
        snap = self.m.snapshot()
        self.assertAlmostEqual(snap["avg_processing_ms"], 200.0)

    def test_provider_failure_counter(self):
        self.m.record_provider_call("ComicVine", 200.0, success=False)
        snap = self.m.snapshot()
        self.assertEqual(snap["provider_failures"], 1)
        self.assertEqual(snap["providers"]["ComicVine"]["failure_count"], 1)

    def test_cache_hit_rate(self):
        self.m.record_cache_hit("ComicVine")
        self.m.record_cache_hit("ComicVine")
        self.m.record_cache_miss("ComicVine")
        snap = self.m.snapshot()
        # 2 hits / 3 total = 66.7%
        self.assertAlmostEqual(snap["providers"]["ComicVine"]["cache_hit_rate"], 66.7, places=0)

    def test_provider_avg_response_ms(self):
        self.m.record_provider_call("CV", 100.0, success=True)
        self.m.record_provider_call("CV", 300.0, success=True)
        snap = self.m.snapshot()
        self.assertAlmostEqual(snap["providers"]["CV"]["avg_response_ms"], 200.0)

    def test_thread_safe_concurrent_records(self):
        def worker():
            for _ in range(50):
                self.m.record_job_result("SUCCESS", duration_ms=10.0)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = self.m.snapshot()
        self.assertEqual(snap["files_processed"], 200)
        self.assertEqual(snap["files_resolved"], 200)

    def test_archive_failure_counter(self):
        self.m.record_archive_failure()
        self.m.record_archive_failure()
        snap = self.m.snapshot()
        self.assertEqual(snap["archive_failures"], 2)

    def test_reset_clears_all(self):
        self.m.record_job_result("SUCCESS")
        self.m.record_provider_call("CV", 100.0)
        self.m.reset()
        snap = self.m.snapshot()
        self.assertEqual(snap["files_processed"], 0)
        self.assertEqual(snap["providers"], {})


# ===================================================================== #
# Phase 35 — Rate Limiter                                               #
# ===================================================================== #
class TestRateLimiter(unittest.TestCase):

    def test_unlimited_provider_always_acquires(self):
        registry = RateLimiterRegistry()
        # Kapowarr is not in defaults so it's unlimited
        for _ in range(20):
            self.assertTrue(registry.acquire("Kapowarr", timeout=0.0))

    def test_high_rate_provider_acquires_quickly(self):
        registry = RateLimiterRegistry()
        registry.configure("FastProvider", rate_per_second=1000.0, burst=50)
        start = time.monotonic()
        for _ in range(10):
            self.assertTrue(registry.acquire("FastProvider", timeout=1.0))
        elapsed = time.monotonic() - start
        # 10 tokens from a burst-50 bucket at 1000/s should be near-instant
        self.assertLess(elapsed, 0.5)

    def test_slow_rate_provider_throttles(self):
        registry = RateLimiterRegistry()
        # 5 tokens/sec, burst 1 — second acquire must wait ~0.2s
        registry.configure("SlowProvider", rate_per_second=5.0, burst=1)
        registry.acquire("SlowProvider", timeout=1.0)   # consume the burst
        start = time.monotonic()
        acquired = registry.acquire("SlowProvider", timeout=1.0)
        elapsed = time.monotonic() - start
        self.assertTrue(acquired)
        # Must have waited at least ~0.1s (generous lower bound for CI)
        self.assertGreater(elapsed, 0.05)

    def test_timeout_returns_false(self):
        registry = RateLimiterRegistry()
        # 0.01 tokens/sec, burst 1 — second acquire will time out in 0.05s
        registry.configure("StarvingProvider", rate_per_second=0.01, burst=1)
        registry.acquire("StarvingProvider", timeout=1.0)  # drain
        result = registry.acquire("StarvingProvider", timeout=0.05)
        self.assertFalse(result)

    def test_comicvine_default_registered(self):
        registry = RateLimiterRegistry()
        # ComicVine default limiter should be created on first acquire
        result = registry.acquire("ComicVine", timeout=5.0)
        self.assertTrue(result)

    def test_remove_makes_unlimited(self):
        registry = RateLimiterRegistry()
        registry.configure("TestProvider", rate_per_second=0.001, burst=1)
        registry.acquire("TestProvider", timeout=1.0)  # drain
        registry.remove("TestProvider")
        # After removal, should be unlimited
        result = registry.acquire("TestProvider", timeout=0.0)
        self.assertTrue(result)


# ===================================================================== #
# Phase 36 — Retry Policy                                               #
# ===================================================================== #
class TestRetryPolicy(unittest.TestCase):

    def test_retryable_exception_classifies_timeout(self):
        self.assertTrue(is_retryable_exception(TimeoutError()))
        self.assertTrue(is_retryable_exception(ConnectionResetError()))

    def test_retryable_http_429(self):
        err = urllib.error.HTTPError(url="", code=429, msg="", hdrs=None, fp=None)
        self.assertTrue(is_retryable_exception(err))

    def test_retryable_http_503(self):
        err = urllib.error.HTTPError(url="", code=503, msg="", hdrs=None, fp=None)
        self.assertTrue(is_retryable_exception(err))

    def test_not_retryable_http_404(self):
        err = urllib.error.HTTPError(url="", code=404, msg="", hdrs=None, fp=None)
        self.assertFalse(is_retryable_exception(err))

    def test_not_retryable_http_401(self):
        err = urllib.error.HTTPError(url="", code=401, msg="", hdrs=None, fp=None)
        self.assertFalse(is_retryable_exception(err))

    def test_retryable_error_marker(self):
        self.assertTrue(is_retryable_exception(RetryableError("temporary")))

    def test_non_retryable_error_marker(self):
        self.assertFalse(is_retryable_exception(NonRetryableError("parse failed")))

    def test_classify_http_error_raises_retryable_for_429(self):
        with self.assertRaises(RetryableError):
            classify_http_error(429, "https://example.com")

    def test_classify_http_error_raises_non_retryable_for_404(self):
        with self.assertRaises(NonRetryableError):
            classify_http_error(404, "https://example.com")

    def test_decorator_retries_retryable_exception(self):
        call_count = [0]

        @with_retry(max_attempts=3, base_delay=0.001, provider="TestProvider")
        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise RetryableError("temporary")
            return "ok"

        result = flaky()
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)

    def test_decorator_does_not_retry_non_retryable(self):
        call_count = [0]

        @with_retry(max_attempts=5, base_delay=0.001, provider="TestProvider")
        def always_bad():
            call_count[0] += 1
            raise NonRetryableError("404 not found")

        with self.assertRaises(NonRetryableError):
            always_bad()
        self.assertEqual(call_count[0], 1)  # Never retried

    def test_decorator_exhausts_retries_and_raises(self):
        call_count = [0]

        @with_retry(max_attempts=3, base_delay=0.001, provider="TestProvider")
        def always_timeout():
            call_count[0] += 1
            raise TimeoutError("connection timed out")

        with self.assertRaises(TimeoutError):
            always_timeout()
        self.assertEqual(call_count[0], 3)

    def test_decorator_passes_through_success_on_first_try(self):
        @with_retry(max_attempts=3, base_delay=0.001)
        def always_ok():
            return 42

        self.assertEqual(always_ok(), 42)


if __name__ == "__main__":
    unittest.main()
