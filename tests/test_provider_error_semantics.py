"""
tests/test_provider_error_semantics.py — Phase 83: Provider Error Semantics Tests

Verifies:
1. 83.1: Provider errors are never swallowed/converted into None.
2. 83.2: Standardized ProviderOperationResult structure.
3. 83.3: Strict classification of retryable vs non-retryable errors.
4. 83.4: Error preservation through MetadataResolver and ResolutionResult.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from cache.db import CacheManager
from models.comic import Comic
from models.identity import ComicIdentity
from observability.retry import (
    classify_provider_error,
    is_retryable_exception,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    ProviderNotFound,
    ProviderAuthError,
    ProviderParseError,
    ProviderInvalidResponse,
    PROVIDER_STATE_RATE_LIMITED,
    PROVIDER_STATE_TIMEOUT,
    PROVIDER_STATE_SERVER_ERROR,
    PROVIDER_STATE_NOT_FOUND,
    PROVIDER_STATE_AUTH_FAILED,
    PROVIDER_STATE_PARSE_ERROR,
    PROVIDER_STATE_INVALID_RESPONSE
)
from pipeline.resolver import (
    MetadataResolver,
    ProviderOperationResult,
    MetadataRetrievalResult,
    STATE_METADATA_FOUND,
    STATE_METADATA_NOT_FOUND,
    STATE_METADATA_PROVIDER_ERROR,
    STATE_METADATA_INVALID
)
from providers.base import (
    ProviderError,
    ProviderConnectionError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    MetadataNotFoundError
)
from providers.comicvine.provider import ComicVineProvider
from providers.gcd.provider import GCPProvider


class TestProviderErrorSemantics(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase83_err_")
        self.cache_path = os.path.join(self.tmp, "cache.db")
        self.cache_mgr = CacheManager(self.cache_path)

        self.mock_kapowarr = MagicMock()
        self.mock_comicvine = MagicMock()
        self.mock_gcp = MagicMock()

        self.resolver = MetadataResolver(
            cache_mgr=self.cache_mgr,
            kapowarr=self.mock_kapowarr,
            comicvine=self.mock_comicvine,
            gcp=self.mock_gcp
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # 83.1: Never Convert Provider Errors into None                      #
    # ------------------------------------------------------------------ #
    def test_83_1_comicvine_lookup_propagates_exceptions(self):
        """83.1: ComicVineProvider.lookup_issue raises ProviderRateLimitError instead of returning None."""
        cv_provider = ComicVineProvider()
        with patch.object(cv_provider.client, "fetch_html", side_effect=ProviderRateLimitError("Rate limited", provider_name="CV")):
            with self.assertRaises(ProviderRateLimitError):
                cv_provider.lookup_issue("4000-12345")

    def test_83_1_gcd_lookup_propagates_exceptions(self):
        """83.1: GCPProvider.lookup_issue raises ProviderConnectionError instead of returning None."""
        gcp_provider = GCPProvider()
        with patch.object(gcp_provider, "_scrape_issue", side_effect=ProviderConnectionError("Connection failed", provider_name="GCP")):
            with self.assertRaises(ProviderConnectionError):
                gcp_provider.lookup_issue("12345")

    # ------------------------------------------------------------------ #
    # 83.2: Standardize Provider Result Structure                        #
    # ------------------------------------------------------------------ #
    def test_83_2_provider_operation_result_structure(self):
        """83.2: ProviderOperationResult follows unified structure with status, retryable, error_code, data."""
        success_res = ProviderOperationResult(
            provider="ComicVine",
            operation="search_issue",
            status="SUCCESS",
            data=[{"title": "Batman #1"}]
        )
        self.assertEqual(success_res.status, "SUCCESS")
        self.assertFalse(success_res.retryable)
        self.assertIsNone(success_res.error_code)

        fail_res = ProviderOperationResult(
            provider="ComicVine",
            operation="search_issue",
            status="RATE_LIMITED",
            error_type="ProviderRateLimited",
            error_code="RATE_LIMITED",
            retryable=True,
            message="HTTP 429 Too Many Requests"
        )
        self.assertEqual(fail_res.status, "RATE_LIMITED")
        self.assertTrue(fail_res.retryable)
        self.assertEqual(fail_res.error_code, "RATE_LIMITED")

        d = fail_res.to_dict()
        self.assertEqual(d["status"], "RATE_LIMITED")
        self.assertEqual(d["error_code"], "RATE_LIMITED")
        self.assertTrue(d["retryable"])

    # ------------------------------------------------------------------ #
    # 83.3: Retry Policy Classification                                  #
    # ------------------------------------------------------------------ #
    def test_83_3_retryable_error_classification(self):
        """83.3: Rate limits, timeouts, and connection errors are classified as retryable."""
        self.assertTrue(is_retryable_exception(ProviderRateLimited("Rate limit")))
        self.assertTrue(is_retryable_exception(ProviderRateLimitError("Rate limit")))
        self.assertTrue(is_retryable_exception(ProviderTimeout("Timed out")))
        self.assertTrue(is_retryable_exception(ProviderUnavailable("503 Service Unavailable")))
        self.assertTrue(is_retryable_exception(ProviderConnectionError("Connection reset")))

        state, retryable = classify_provider_error(ProviderRateLimited("Rate limit"), provider="CV")
        self.assertEqual(state, PROVIDER_STATE_RATE_LIMITED)
        self.assertTrue(retryable)

        state, retryable = classify_provider_error(ProviderTimeout("Timeout"), provider="Kapowarr")
        self.assertEqual(state, PROVIDER_STATE_TIMEOUT)
        self.assertTrue(retryable)

    def test_83_3_non_retryable_error_classification(self):
        """83.3: Auth errors, 404 Not Found, and parse errors are classified as non-retryable."""
        self.assertFalse(is_retryable_exception(ProviderAuthError("Unauthorized")))
        self.assertFalse(is_retryable_exception(ProviderAuthenticationError("Invalid API key")))
        self.assertFalse(is_retryable_exception(ProviderNotFound("404 Not Found")))
        self.assertFalse(is_retryable_exception(MetadataNotFoundError("Missing item")))
        self.assertFalse(is_retryable_exception(ProviderParseError("Malformed XML")))
        self.assertFalse(is_retryable_exception(ProviderInvalidResponse("Missing fields")))

        state, retryable = classify_provider_error(ProviderAuthError("Auth error"), provider="CV")
        self.assertEqual(state, PROVIDER_STATE_AUTH_FAILED)
        self.assertFalse(retryable)

        state, retryable = classify_provider_error(ProviderNotFound("Not found"), provider="Kapowarr")
        self.assertEqual(state, PROVIDER_STATE_NOT_FOUND)
        self.assertFalse(retryable)

        state, retryable = classify_provider_error(ProviderParseError("Parse error"), provider="GCP")
        self.assertEqual(state, PROVIDER_STATE_PARSE_ERROR)
        self.assertFalse(retryable)

    # ------------------------------------------------------------------ #
    # 83.4: Preserve Provider Errors Through Resolver                    #
    # ------------------------------------------------------------------ #
    def test_83_4_retrieve_metadata_distinguishes_not_found_from_error(self):
        """83.4: retrieve_metadata_result preserves METADATA_PROVIDER_ERROR when provider throws."""
        identity = ComicIdentity(provider="ComicVine", issue_id="4000-9999")

        # 1. Simulate provider exception (Rate Limited)
        self.mock_comicvine.lookup_issue.side_effect = ProviderRateLimited("Rate limit hit")

        res_error = self.resolver.retrieve_metadata_result(identity)
        self.assertEqual(res_error.state, STATE_METADATA_PROVIDER_ERROR)
        self.assertIn("Rate limit", res_error.error_message)

        # 2. Simulate provider returning None (Legitimate Not Found)
        self.mock_comicvine.lookup_issue.side_effect = None
        self.mock_comicvine.lookup_issue.return_value = None

        res_not_found = self.resolver.retrieve_metadata_result(identity)
        self.assertEqual(res_not_found.state, STATE_METADATA_NOT_FOUND)

    def test_83_4_resolver_records_provider_error_status_in_results(self):
        """83.4: resolve_identity records explicit provider error statuses in provider_results."""
        self.mock_kapowarr.test_connection.return_value = True
        self.mock_kapowarr.search_issue.side_effect = ProviderTimeout("Kapowarr timeout")

        self.mock_comicvine.search_issue.side_effect = ProviderRateLimited("ComicVine 429")

        identity, decision = self.resolver.resolve_identity("Batman #001 (2016).cbz")

        self.assertIn("Kapowarr", decision.provider_results)
        self.assertEqual(decision.provider_results["Kapowarr"].status, PROVIDER_STATE_TIMEOUT)
        self.assertTrue(decision.provider_results["Kapowarr"].retryable)

        self.assertIn("ComicVine", decision.provider_results)
        self.assertEqual(decision.provider_results["ComicVine"].status, PROVIDER_STATE_RATE_LIMITED)
        self.assertTrue(decision.provider_results["ComicVine"].retryable)


if __name__ == "__main__":
    unittest.main()
