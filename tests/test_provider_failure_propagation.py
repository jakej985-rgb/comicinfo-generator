"""
Phase 57 — Make Provider Failure State Survive the Pipeline Tests

Verifies:
1. Provider search NOT_FOUND is preserved as status="NOT_FOUND", retryable=False
2. Provider search TIMEOUT is preserved as status="TIMEOUT", retryable=True
3. Provider search 500 is preserved as status="SERVER_ERROR", retryable=True
4. Provider search 429 is preserved as status="RATE_LIMITED", retryable=True
5. Provider search 401 is preserved as status="AUTH_FAILED", retryable=False
6. Kapowarr OFFLINE connection failure is preserved as status="OFFLINE"
7. Successful provider search is preserved as status="SUCCESS"
8. resolve_file_pipeline returns ResolutionResult with complete provider_results map
"""
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

import config
from models.comic import Comic
from models.identity import ComicIdentity
from cache.db import CacheManager
from pipeline.resolver import (
    MetadataResolver,
    ProviderOperationResult,
    ResolutionResult,
    STATE_METADATA_FOUND
)
from observability.retry import (
    ProviderUnavailable,
    ProviderTimeout,
    ProviderRateLimited,
    ProviderAuthError,
    ProviderNotFound
)


class TestProviderFailurePropagation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "prov_prop.db")
        self.cache = CacheManager(db_path=self.db_path)
        self.cfg = config.load_config()
        self.cfg.cache.db_path = self.db_path

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_sample_cbz(self, name: str) -> str:
        cbz_path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(cbz_path), exist_ok=True)
        with zipfile.ZipFile(cbz_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"page1")
        return cbz_path

    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_provider_not_found_vs_offline_propagation(self, MockGCP, MockKap, MockCV):
        """Kapowarr OFFLINE, ComicVine NOT_FOUND, GCP SUCCESS preserves distinct statuses."""
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.search_issue.return_value = [
            {"id": "gcd-123", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        MockGCP.return_value.lookup_issue.return_value = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_sample_cbz("Batman #001 (2016).cbz")

        res: ResolutionResult = resolver.resolve_file_pipeline(cbz)
        self.assertIsNotNone(res)
        self.assertIn("Kapowarr", res.provider_results)
        self.assertEqual(res.provider_results["Kapowarr"].status, "OFFLINE")

        self.assertIn("ComicVine", res.provider_results)
        self.assertEqual(res.provider_results["ComicVine"].status, "NOT_FOUND")

        self.assertIn("GCP", res.provider_results)
        self.assertEqual(res.provider_results["GCP"].status, "SUCCESS")

        self.assertIsNotNone(res.comic)
        self.assertEqual(res.identity.provider, "GCP")

    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_provider_server_error_and_rate_limited_propagation(self, MockGCP, MockKap, MockCV):
        """Kapowarr SERVER_ERROR (500), ComicVine RATE_LIMITED (429) preserves retryable states."""
        MockKap.return_value.test_connection.return_value = True
        MockKap.return_value.search_issue.side_effect = ProviderUnavailable("HTTP 500 Internal Server Error")
        MockCV.return_value.search_issue.side_effect = ProviderRateLimited("HTTP 429 Rate Limited")
        MockGCP.return_value.search_issue.return_value = []

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_sample_cbz("Batman #001 (2016).cbz")

        res: ResolutionResult = resolver.resolve_file_pipeline(cbz)
        self.assertIn("Kapowarr", res.provider_results)
        self.assertEqual(res.provider_results["Kapowarr"].status, "SERVER_ERROR")
        self.assertTrue(res.provider_results["Kapowarr"].retryable)

        self.assertIn("ComicVine", res.provider_results)
        self.assertEqual(res.provider_results["ComicVine"].status, "RATE_LIMITED")
        self.assertTrue(res.provider_results["ComicVine"].retryable)

        self.assertIn("GCP", res.provider_results)
        self.assertEqual(res.provider_results["GCP"].status, "NOT_FOUND")
        self.assertFalse(res.provider_results["GCP"].retryable)

    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_provider_auth_error_and_timeout_propagation(self, MockGCP, MockKap, MockCV):
        """ComicVine AUTH_FAILED (401), Kapowarr TIMEOUT preserves non-retryable and retryable states."""
        MockKap.return_value.test_connection.return_value = True
        MockKap.return_value.search_issue.side_effect = ProviderTimeout("Connection Timed Out")
        MockCV.return_value.search_issue.side_effect = ProviderAuthError("HTTP 401 Invalid API Key")
        MockGCP.return_value.search_issue.return_value = []

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_sample_cbz("Batman #001 (2016).cbz")

        res: ResolutionResult = resolver.resolve_file_pipeline(cbz)
        self.assertIn("Kapowarr", res.provider_results)
        self.assertEqual(res.provider_results["Kapowarr"].status, "TIMEOUT")
        self.assertTrue(res.provider_results["Kapowarr"].retryable)

        self.assertIn("ComicVine", res.provider_results)
        self.assertEqual(res.provider_results["ComicVine"].status, "AUTH_FAILED")
        self.assertFalse(res.provider_results["ComicVine"].retryable)


if __name__ == "__main__":
    unittest.main()
