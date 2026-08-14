"""
tests/test_provider_resolution_redesign.py — Phase 82: Provider Resolution Redesign Tests

Verifies:
1. 82.1: Authoritative Resolution Order
2. 82.2: Existing ComicInfo as authoritative evidence without network calls
3. 82.3: Cache checked before calling network providers
4. 82.4: Kapowarr-First behavior (no ComicVine request if Kapowarr resolves with high confidence)
5. 82.5: ComicVine fallback behavior and reason tracking
6. 82.6: GCD fallback behavior when earlier stages fail
7. 82.7: Provider resolution reason exposure (resolution_source, fallback_used, fallback_reason)
"""

import io
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from config import Config
from models.comic import Comic
from models.identity import ComicIdentity
from cache.db import CacheManager
from pipeline.resolver import MetadataResolver
from writers.comicinfo import generate_xml_bytes


class TestProviderResolutionRedesign(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="phase82_res_")
        self.cache_path = os.path.join(self.tmp, "cache.db")
        self.cache_mgr = CacheManager(self.cache_path)

        # Mock providers
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

    def _create_dummy_cbz(self, fname: str, comic: Comic = None) -> str:
        cbz_path = os.path.join(self.tmp, fname)
        with zipfile.ZipFile(cbz_path, "w") as zf:
            if comic:
                xml_data = generate_xml_bytes(comic)
                zf.writestr("ComicInfo.xml", xml_data)
            zf.writestr("001.jpg", b"image data")
        return cbz_path

    # ------------------------------------------------------------------ #
    # 82.1 & 82.7: URL Override takes immediate precedence              #
    # ------------------------------------------------------------------ #
    def test_82_1_url_override_precedence(self):
        """82.1: Explicit URL override resolves immediately with 100% confidence without provider searches."""
        url = "https://comicvine.gamespot.com/batman-1/4000-534927/"
        identity, decision = self.resolver.resolve_identity("Batman #001 (2016).cbz", url_override=url)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.issue_id, "4000-534927")
        self.assertEqual(identity.resolution_source, "url_override")
        self.assertFalse(identity.fallback_used)
        self.assertEqual(decision.score, 100.0)

        # Providers must not be searched
        self.mock_kapowarr.search_issue.assert_not_called()
        self.mock_comicvine.search_issue.assert_not_called()
        self.mock_gcp.search_issue.assert_not_called()

    # ------------------------------------------------------------------ #
    # 82.2: Existing ComicInfo.xml as Authoritative Evidence              #
    # ------------------------------------------------------------------ #
    def test_82_2_valid_existing_comicinfo_avoids_network_calls(self):
        """82.2: Valid, consistent existing ComicInfo.xml with provider provenance resolves locally with zero provider calls."""
        comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics", web="https://comicvine.gamespot.com/issue/4000-534927/")
        cbz_path = self._create_dummy_cbz("Batman #001 (2016).cbz", comic=comic)

        identity, decision = self.resolver.resolve_identity(cbz_path)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.series_name, "Batman")
        self.assertEqual(identity.issue_number, "1")
        self.assertEqual(identity.issue_id, "4000-534927")
        self.assertEqual(identity.resolution_source, "existing_comicinfo")
        self.assertFalse(identity.fallback_used)
        self.assertEqual(decision.resolution_source, "existing_comicinfo")
        self.assertGreaterEqual(decision.score, 80.0)

        # Zero network provider calls
        self.mock_kapowarr.search_issue.assert_not_called()
        self.mock_comicvine.search_issue.assert_not_called()
        self.mock_gcp.search_issue.assert_not_called()

    def test_82_2_conflicting_existing_comicinfo_does_not_short_circuit(self):
        """82.2: Conflicting existing ComicInfo.xml (e.g. wrong issue) falls through to provider search."""
        comic = Comic(series="Batman", number="999", year=2016)  # Conflicts with #001
        cbz_path = self._create_dummy_cbz("Batman #001 (2016).cbz", comic=comic)

        self.mock_kapowarr.test_connection.return_value = True
        self.mock_kapowarr.search_issue.return_value = [
            {"id": "kap-101", "series": "Batman", "number": "1", "year": 2016, "publisher": "DC Comics"}
        ]

        identity, decision = self.resolver.resolve_identity(cbz_path)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "Kapowarr")
        self.assertEqual(identity.issue_id, "kap-101")
        self.assertEqual(identity.resolution_source, "kapowarr")
        self.mock_kapowarr.search_issue.assert_called_once()

    # ------------------------------------------------------------------ #
    # 82.3: Cache Checked Before Network Providers                       #
    # ------------------------------------------------------------------ #
    def test_82_3_cache_lookup_avoids_network_calls(self):
        """82.3: Valid persistent cache entry resolves without network requests."""
        fname = "Flash #001 (2016).cbz"
        cbz_path = self._create_dummy_cbz(fname)

        # Pre-populate search cache
        cached_results = [{
            "provider": "Kapowarr",
            "issue_id": "kap-flash-1",
            "series_name": "The Flash",
            "issue_number": "1",
            "publication_year": 2016,
            "publisher": "DC Comics"
        }]
        self.cache_mgr.save_cached_search("Kapowarr", "issue", fname.lower(), cached_results)

        identity, decision = self.resolver.resolve_identity(cbz_path)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.issue_id, "kap-flash-1")
        self.assertEqual(identity.resolution_source, "persistent_cache")
        self.assertFalse(identity.fallback_used)
        self.assertEqual(decision.resolution_source, "persistent_cache")

        # Zero network provider calls
        self.mock_kapowarr.search_issue.assert_not_called()
        self.mock_comicvine.search_issue.assert_not_called()
        self.mock_gcp.search_issue.assert_not_called()

    # ------------------------------------------------------------------ #
    # 82.4: Kapowarr-First Behavior                                      #
    # ------------------------------------------------------------------ #
    def test_82_4_kapowarr_first_avoids_comicvine_request(self):
        """82.4: When Kapowarr resolves the comic with high confidence, ComicVine is NOT queried."""
        cbz_path = self._create_dummy_cbz("Nightwing #001 (2016).cbz")

        self.mock_kapowarr.test_connection.return_value = True
        self.mock_kapowarr.search_issue.return_value = [
            {"id": "kap-nw-1", "series": "Nightwing", "number": "1", "year": 2016, "publisher": "DC Comics"}
        ]

        identity, decision = self.resolver.resolve_identity(cbz_path)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "Kapowarr")
        self.assertEqual(identity.resolution_source, "kapowarr")
        self.assertFalse(identity.fallback_used)

        # Verified: Kapowarr was called, ComicVine and GCD were NOT called
        self.mock_kapowarr.search_issue.assert_called_once()
        self.mock_comicvine.search_issue.assert_not_called()
        self.mock_gcp.search_issue.assert_not_called()

    # ------------------------------------------------------------------ #
    # 82.5: ComicVine Fallback with Reason Tracking                      #
    # ------------------------------------------------------------------ #
    def test_82_5_comicvine_fallback_when_kapowarr_misses(self):
        """82.5: When Kapowarr returns no results, ComicVine is queried as fallback and reasons are recorded."""
        cbz_path = self._create_dummy_cbz("Saga #001 (2012).cbz")

        self.mock_kapowarr.test_connection.return_value = True
        self.mock_kapowarr.search_issue.return_value = []  # No match in Kapowarr

        self.mock_comicvine.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-324567/", "series": "Saga", "number": "1", "year": 2012, "publisher": "Image"}
        ]

        identity, decision = self.resolver.resolve_identity(cbz_path)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "ComicVine")
        self.assertEqual(identity.resolution_source, "comicvine_fallback")
        self.assertTrue(identity.fallback_used)
        self.assertIn("Kapowarr returned no match", identity.fallback_reason)

        # Both Kapowarr and ComicVine called, GCP not called
        self.mock_kapowarr.search_issue.assert_called_once()
        self.mock_comicvine.search_issue.assert_called_once()
        self.mock_gcp.search_issue.assert_not_called()

    def test_82_5_comicvine_fallback_when_kapowarr_offline(self):
        """82.5: When Kapowarr is offline, ComicVine is queried as fallback with clear offline reason."""
        cbz_path = self._create_dummy_cbz("Spawn #001 (1992).cbz")

        self.mock_kapowarr.test_connection.return_value = False  # Offline

        self.mock_comicvine.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-11111/", "series": "Spawn", "number": "1", "year": 1992, "publisher": "Image"}
        ]

        identity, decision = self.resolver.resolve_identity(cbz_path)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "ComicVine")
        self.assertEqual(identity.resolution_source, "comicvine_fallback")
        self.assertTrue(identity.fallback_used)
        self.assertIn("offline", identity.fallback_reason.lower())

    # ------------------------------------------------------------------ #
    # 82.6: GCD Fallback                                                 #
    # ------------------------------------------------------------------ #
    def test_82_6_gcd_fallback_when_earlier_providers_fail(self):
        """82.6: When Kapowarr and ComicVine fail to resolve, GCD is queried as second-line fallback."""
        cbz_path = self._create_dummy_cbz("Rare Indie #001 (2020).cbz")

        self.mock_kapowarr.test_connection.return_value = True
        self.mock_kapowarr.search_issue.return_value = []
        self.mock_comicvine.search_issue.return_value = []  # ComicVine also no match

        self.mock_gcp.search_issue.return_value = [
            {"id": "gcd-9999", "series": "Rare Indie", "number": "1", "year": 2020, "publisher": "Indie Press"}
        ]

        identity, decision = self.resolver.resolve_identity(cbz_path)

        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "GCP")
        self.assertEqual(identity.resolution_source, "gcd_fallback")
        self.assertTrue(identity.fallback_used)

        self.mock_kapowarr.search_issue.assert_called_once()
        self.mock_comicvine.search_issue.assert_called_once()
        self.mock_gcp.search_issue.assert_called_once()

    # ------------------------------------------------------------------ #
    # 82.7: Comprehensive Pipeline Result Diagnostic Propagation         #
    # ------------------------------------------------------------------ #
    def test_82_7_pipeline_result_exposes_diagnostics(self):
        """82.7: resolve_file_pipeline exposes resolution_source, fallback_used, and fallback_reason."""
        cbz_path = self._create_dummy_cbz("Monstress #001 (2015).cbz")

        self.mock_kapowarr.test_connection.return_value = True
        self.mock_kapowarr.search_issue.return_value = []  # Fallback to ComicVine

        self.mock_comicvine.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-50000/", "series": "Monstress", "number": "1", "year": 2015, "publisher": "Image"}
        ]

        res = self.resolver.resolve_file_pipeline(cbz_path)

        self.assertIsNotNone(res.identity)
        self.assertEqual(res.resolution_source, "comicvine_fallback")
        self.assertTrue(res.fallback_used)
        self.assertIn("Kapowarr returned no match", res.fallback_reason)


if __name__ == "__main__":
    unittest.main()
