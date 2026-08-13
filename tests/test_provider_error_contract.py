"""
Phase 46 — Provider Error Contract Tests (Sections 46.1 - 46.5)

Tests:
1. Timeout error classification (TIMEOUT, retryable)
2. HTTP 404 classification (NOT_FOUND, not retryable)
3. HTTP 401/403 classification (AUTH_FAILED, not retryable)
4. HTTP 429 classification (RATE_LIMITED, retryable)
5. HTTP 500 classification (SERVER_ERROR, retryable)
6. Malformed response / parse failure (PARSE_ERROR, not retryable)
7. Empty search result handling (NOT_FOUND distinction from error)
8. API Key and Secret Redaction from URLs
9. Resolver fallback on provider errors
"""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from config import Config
from cache.db import CacheManager
from observability.retry import (
    classify_http_error,
    classify_provider_error,
    sanitize_log_url,
    RetryableError,
    NonRetryableError,
    ProviderUnavailable,
    ProviderTimeout,
    ProviderRateLimited,
    ProviderNotFound,
    ProviderAuthError,
    ProviderParseError,
    ProviderInvalidResponse,
    PROVIDER_STATE_FOUND,
    PROVIDER_STATE_NOT_FOUND,
    PROVIDER_STATE_OFFLINE,
    PROVIDER_STATE_TIMEOUT,
    PROVIDER_STATE_RATE_LIMITED,
    PROVIDER_STATE_AUTH_FAILED,
    PROVIDER_STATE_SERVER_ERROR,
    PROVIDER_STATE_PARSE_ERROR,
    PROVIDER_STATE_INVALID_RESPONSE
)
from pipeline.resolver import MetadataResolver


class TestProviderErrorContract(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config = Config()
        self.config.cache.db_path = os.path.join(self.tmp, "contract_test.db")
        self.cache = CacheManager(self.config.cache.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # 46.5.1: Timeout
    def test_timeout_classification(self):
        exc = TimeoutError("Connection timed out")
        state, retryable = classify_provider_error(exc, provider="ComicVine", operation="search_issue")
        self.assertEqual(state, PROVIDER_STATE_TIMEOUT)
        self.assertTrue(retryable)

        prov_timeout = ProviderTimeout("Custom provider timeout")
        state2, retryable2 = classify_provider_error(prov_timeout, provider="Kapowarr", operation="get_issue")
        self.assertEqual(state2, PROVIDER_STATE_TIMEOUT)
        self.assertTrue(retryable2)

    # 46.5.2: HTTP 404
    def test_http_404_classification(self):
        with self.assertRaises(ProviderNotFound):
            classify_http_error(404, "https://comicvine.gamespot.com/api/issue/4000-999999/")

        exc = ProviderNotFound("Not Found")
        state, retryable = classify_provider_error(exc, provider="ComicVine", operation="lookup_issue")
        self.assertEqual(state, PROVIDER_STATE_NOT_FOUND)
        self.assertFalse(retryable)

    # 46.5.3: HTTP 401 & 403
    def test_http_auth_error_classification(self):
        with self.assertRaises(ProviderAuthError):
            classify_http_error(401, "https://comicvine.gamespot.com/api/search/")

        with self.assertRaises(ProviderAuthError):
            classify_http_error(403, "https://comicvine.gamespot.com/api/search/")

        exc = ProviderAuthError("Unauthorized")
        state, retryable = classify_provider_error(exc, provider="ComicVine", operation="search_issue")
        self.assertEqual(state, PROVIDER_STATE_AUTH_FAILED)
        self.assertFalse(retryable)

    # 46.5.4: HTTP 429
    def test_http_429_classification(self):
        with self.assertRaises(ProviderRateLimited):
            classify_http_error(429, "https://comicvine.gamespot.com/api/search/")

        exc = ProviderRateLimited("Too Many Requests")
        state, retryable = classify_provider_error(exc, provider="ComicVine", operation="search_issue")
        self.assertEqual(state, PROVIDER_STATE_RATE_LIMITED)
        self.assertTrue(retryable)

    # 46.5.5: HTTP 500
    def test_http_500_classification(self):
        with self.assertRaises(ProviderUnavailable):
            classify_http_error(500, "https://comicvine.gamespot.com/api/search/")

        with self.assertRaises(ProviderUnavailable):
            classify_http_error(503, "https://comicvine.gamespot.com/api/search/")

        exc = ProviderUnavailable("Internal Server Error")
        state, retryable = classify_provider_error(exc, provider="Kapowarr", operation="search_issue")
        self.assertEqual(state, PROVIDER_STATE_SERVER_ERROR)
        self.assertTrue(retryable)

    # 46.5.6: Malformed response / Parse error
    def test_parse_error_classification(self):
        exc = ProviderParseError("Malformed XML/JSON from provider")
        state, retryable = classify_provider_error(exc, provider="ComicVine", operation="parse_response")
        self.assertEqual(state, PROVIDER_STATE_PARSE_ERROR)
        self.assertFalse(retryable)

        exc_inv = ProviderInvalidResponse("Payload missing expected fields")
        state_inv, retryable_inv = classify_provider_error(exc_inv, provider="GCP", operation="search_issue")
        self.assertEqual(state_inv, PROVIDER_STATE_INVALID_RESPONSE)
        self.assertFalse(retryable_inv)

    # 46.5.7: Empty search result handling
    def test_empty_search_result_handling(self):
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):

            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.return_value = [] # Empty search (NOT_FOUND)
            MockCV.return_value.search_issue.return_value = []  # Empty search (NOT_FOUND)

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity("Unknown_Comic_9999.cbz")

            # Must resolve as None with SKIP action without raising unhandled exceptions
            self.assertIsNone(identity)
            self.assertEqual(decision.action, "SKIP")

    # 46.5.8: Safe URL Redaction (Never log API keys)
    def test_sanitize_log_url_redacts_credentials(self):
        url_with_api_key = "https://comicvine.gamespot.com/api/search/?api_key=SECRET123456&format=json&query=batman"
        clean = sanitize_log_url(url_with_api_key)
        self.assertNotIn("SECRET123456", clean)
        self.assertIn("api_key=%5BREDACTED%5D", clean)
        self.assertIn("query=batman", clean)

        url_with_token = "http://kapowarr.local:5656/api/v1/search?token=MY_TOP_SECRET_TOKEN&q=spiderman"
        clean_token = sanitize_log_url(url_with_token)
        self.assertNotIn("MY_TOP_SECRET_TOKEN", clean_token)
        self.assertIn("token=%5BREDACTED%5D", clean_token)

    # 46.5.9: Resolver fallback on provider error
    def test_resolver_fallback_on_provider_error(self):
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):

            # Kapowarr crashes with 500 error
            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.side_effect = ProviderUnavailable("HTTP 500 Internal Server Error")

            # ComicVine succeeds
            MockCV.return_value.search_issue.return_value = [
                {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
            ]

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity("Batman (2016)/Batman #001 (2016).cbz")

            # Successfully falls back to ComicVine without aborting
            self.assertIsNotNone(identity)
            self.assertEqual(identity.series_name, "Batman")
            self.assertEqual(identity.issue_number, "1")
            self.assertEqual(identity.provider, "ComicVine")


if __name__ == "__main__":
    unittest.main()
