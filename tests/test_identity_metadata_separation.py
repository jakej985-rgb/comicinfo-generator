"""
Phase 56 — Separate Identity Resolution From Metadata Success Tests

Verifies:
1. Resolved identity + successful metadata retrieval -> STATE_METADATA_FOUND, is_complete=True
2. Resolved identity + provider lookup failure (500/timeout) -> STATE_METADATA_PROVIDER_ERROR, comic is None
3. Resolved identity + provider not found (404/None) -> STATE_METADATA_NOT_FOUND, comic is None
4. Resolved identity + malformed metadata -> STATE_METADATA_INVALID, comic is None
5. resolve_file_metadata returns None when metadata retrieval fails
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
    STATE_METADATA_FOUND,
    STATE_METADATA_NOT_FOUND,
    STATE_METADATA_PROVIDER_ERROR,
    STATE_METADATA_INVALID,
    STATE_METADATA_PARTIAL,
    MetadataRetrievalResult
)
from observability.retry import ProviderUnavailable, ProviderTimeout


class TestIdentityMetadataSeparation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "meta_sep.db")
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
    def test_provider_lookup_succeeds_valid_metadata(self, MockCV):
        """Identity resolved + provider returns valid Comic -> STATE_METADATA_FOUND."""
        MockCV.return_value.lookup_issue.return_value = Comic(
            series="Batman",
            number="1",
            year=2016,
            publisher="DC Comics",
            title="I Am Gotham Part 1"
        )
        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        identity = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1001",
            series_name="Batman",
            issue_number="1"
        )

        res = resolver.retrieve_metadata_result(identity)
        self.assertEqual(res.state, STATE_METADATA_FOUND)
        self.assertTrue(res.is_complete)
        self.assertIsNotNone(res.comic)
        self.assertEqual(res.comic.title, "I Am Gotham Part 1")
        self.assertTrue(res.comic.metadata_complete)

        # Legacy retrieve_metadata returns Comic
        comic = resolver.retrieve_metadata(identity)
        self.assertIsNotNone(comic)
        self.assertEqual(comic.title, "I Am Gotham Part 1")

    @patch("pipeline.resolver.ComicVineProvider")
    def test_provider_lookup_fails_error_no_synthetic_comic(self, MockCV):
        """Identity resolved + provider raises ProviderUnavailable -> STATE_METADATA_PROVIDER_ERROR, comic is None."""
        MockCV.return_value.lookup_issue.side_effect = ProviderUnavailable("HTTP 500 Server Error")
        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        identity = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1001",
            series_name="Batman",
            issue_number="1",
            publication_year=2016
        )

        res = resolver.retrieve_metadata_result(identity)
        self.assertEqual(res.state, STATE_METADATA_PROVIDER_ERROR)
        self.assertFalse(res.is_complete)
        self.assertIsNone(res.comic)
        self.assertIn("500", res.error_message)

        # Legacy retrieve_metadata MUST return None rather than synthesizing a fake Comic
        comic = resolver.retrieve_metadata(identity)
        self.assertIsNone(comic)

    @patch("pipeline.resolver.KapowarrProvider")
    def test_provider_lookup_returns_not_found(self, MockKap):
        """Identity resolved + provider returns None -> STATE_METADATA_NOT_FOUND, comic is None."""
        MockKap.return_value.lookup_issue.return_value = None
        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        identity = ComicIdentity(
            provider="Kapowarr",
            issue_id="kap-999",
            series_name="Batman",
            issue_number="1"
        )

        res = resolver.retrieve_metadata_result(identity)
        self.assertEqual(res.state, STATE_METADATA_NOT_FOUND)
        self.assertFalse(res.is_complete)
        self.assertIsNone(res.comic)

        comic = resolver.retrieve_metadata(identity)
        self.assertIsNone(comic)

    @patch("pipeline.resolver.ComicVineProvider")
    def test_provider_lookup_returns_malformed_invalid_metadata(self, MockCV):
        """Identity resolved + provider returns empty/malformed Comic -> STATE_METADATA_INVALID."""
        # Empty comic without series or title
        MockCV.return_value.lookup_issue.return_value = Comic(series="", title="", number="")
        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        identity = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1001",
            series_name="Batman",
            issue_number="1"
        )

        res = resolver.retrieve_metadata_result(identity)
        self.assertEqual(res.state, STATE_METADATA_INVALID)
        self.assertFalse(res.is_complete)
        self.assertIsNone(res.comic)

    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_resolve_file_metadata_fails_cleanly_on_metadata_failure(self, MockGCP, MockKap, MockCV):
        """When identity is AUTO_ACCEPT but metadata retrieval fails, resolve_file_metadata returns None."""
        MockKap.return_value.test_connection.return_value = False
        MockGCP.return_value.search_issue.return_value = []
        # Identity resolution finds a candidate
        MockCV.return_value.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        # But lookup_issue crashes with 500
        MockCV.return_value.lookup_issue.side_effect = ProviderUnavailable("HTTP 500 Server Error")

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_sample_cbz("Batman #001 (2016).cbz")

        comic, provider = resolver.resolve_file_metadata(cbz)
        self.assertIsNone(comic)
        self.assertEqual(provider, "None")


if __name__ == "__main__":
    unittest.main()
