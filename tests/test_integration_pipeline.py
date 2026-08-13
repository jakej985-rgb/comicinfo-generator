"""
Phase 37 — Integration Tests

Tests the complete pipeline end-to-end using mocked providers.
No live internet required. Every stage is exercised:

  CBZ → identity → Kapowarr → ComicVine → scoring
     → ComicInfo → archive replacement → verification → processing state
"""
import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.confidence import ConfidenceDecision
from writers.archive import embed_comicinfo_in_cbz, verify_cbz_archive, ArchiveWriteError
from cache.db import CacheManager
from cache.tracker import mark_file_processed


def _make_cbz(tmp_dir: str, filename: str, images: list = None) -> str:
    """Helper: builds a minimal valid .cbz file with fake images."""
    path = os.path.join(tmp_dir, filename)
    images = images or ["page_001.jpg", "page_002.jpg", "page_003.jpg"]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for img in images:
            zf.writestr(img, b"\xff\xd8\xff" + b"\x00" * 100)  # fake JPEG header
    return path


def _make_comic(series="Batman", number="1", publisher="DC Comics", year=2016) -> Comic:
    return Comic(
        title=f"{series} #{number}",
        series=series,
        number=number,
        publisher=publisher,
        year=year,
        writers=["Tom King"],
        characters=["Batman", "Catwoman"],
        story_arcs=["I Am Gotham"],
        provider_name="ComicVine",
        provider_id="4000-123456"
    )


class TestIntegrationPipelineWithMocks(unittest.TestCase):
    """
    Phase 37: End-to-end integration tests with mocked providers.
    All network calls are intercepted.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "cache.db")
        self.cache = CacheManager(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Stage 1: Archive → ComicInfo embedding + verification              #
    # ------------------------------------------------------------------ #

    def test_full_embed_and_verify_pipeline(self):
        """
        Integration: build CBZ → embed ComicInfo.xml → verify archive integrity
        → confirm ComicInfo.xml is readable inside the archive.
        """
        cbz = _make_cbz(self.tmp, "Batman_001.cbz")
        comic = _make_comic()

        result_path = embed_comicinfo_in_cbz(cbz, comic)

        # Path must be the same file (atomic replacement)
        self.assertEqual(result_path, cbz)

        # Verification must pass
        verify_cbz_archive(cbz)

        # ComicInfo.xml content must be readable and correct
        with zipfile.ZipFile(cbz, "r") as zf:
            names_lower = [n.lower() for n in zf.namelist()]
            self.assertIn("comicinfo.xml", names_lower)
            xml_bytes = zf.read("ComicInfo.xml")
        self.assertIn(b"Batman", xml_bytes)
        self.assertIn(b"Tom King", xml_bytes)

    def test_original_images_preserved_after_embed(self):
        """Integration: original images must all be present after embed."""
        images = ["page_001.jpg", "page_002.jpg", "page_003.jpg"]
        cbz = _make_cbz(self.tmp, "Xmen_001.cbz", images=images)
        comic = _make_comic(series="X-Men")

        embed_comicinfo_in_cbz(cbz, comic)

        with zipfile.ZipFile(cbz, "r") as zf:
            names = [n.lower() for n in zf.namelist()]
        for img in images:
            self.assertIn(img.lower(), names)

    # ------------------------------------------------------------------ #
    # Stage 2: Identity resolution with mocked providers                 #
    # ------------------------------------------------------------------ #

    def test_identity_resolution_with_mocked_comicvine(self):
        """
        Integration: resolver finds identity via mocked ComicVine search,
        retrieves metadata, and returns a valid Comic.
        """
        cbz = _make_cbz(self.tmp, "Batman_001.cbz")

        mock_cv_identity = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-123456",
            issue_provider="ComicVine",
            series_name="Batman",
            issue_number="1",
            confidence=92.0,
            confidence_level="AUTO_ACCEPT"
        )
        mock_comic = _make_comic()

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"), \
             patch("pipeline.resolver.extract_identity_candidates") as mock_cands, \
             patch("pipeline.resolver.evaluate_confidence") as mock_conf:

            # Kapowarr offline
            MockKap.return_value.test_connection.return_value = False

            # ComicVine returns one result
            MockCV.return_value.search_issue.return_value = [
                {"url": "https://comicvine.gamespot.com/batman/4000-123456/", "title": "Batman #1"}
            ]
            MockCV.return_value.lookup_issue.return_value = mock_comic

            mock_cands.return_value = []
            mock_conf.return_value = ConfidenceDecision(score=92.0, action="AUTO_ACCEPT")

            from config import Config
            cfg = Config()
            cfg.kapowarr.url = "http://localhost:5656"
            cfg.kapowarr.api_key = "test"
            cfg.comicvine.api_key = "cv-test"
            cfg.cache.db_path = self.db_path

            from pipeline.resolver import MetadataResolver
            resolver = MetadataResolver(config=cfg, cache_mgr=self.cache)

            comic, provider = resolver.resolve_file_metadata(cbz)

        # Should return a comic from the mock
        self.assertIsNotNone(comic)
        self.assertEqual(provider, "ComicVine")

    def test_kapowarr_wins_over_comicvine_when_online(self):
        """Integration: Kapowarr result takes priority over ComicVine when online."""
        cbz = _make_cbz(self.tmp, "Batman_001.cbz")

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"), \
             patch("pipeline.resolver.extract_identity_candidates") as mock_cands, \
             patch("pipeline.resolver.evaluate_confidence") as mock_conf:

            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.return_value = [
                {"id": "kap-999", "title": "Batman #1"}
            ]
            MockKap.return_value.lookup_issue.return_value = _make_comic()
            MockCV.return_value.search_issue.return_value = []
            mock_cands.return_value = []
            mock_conf.return_value = ConfidenceDecision(score=95.0, action="AUTO_ACCEPT")

            from config import Config
            cfg = Config()
            cfg.cache.db_path = self.db_path

            from pipeline.resolver import MetadataResolver
            resolver = MetadataResolver(config=cfg, cache_mgr=self.cache)
            comic, provider = resolver.resolve_file_metadata(cbz)

        self.assertIsNotNone(comic)
        self.assertEqual(provider, "Kapowarr")

    # ------------------------------------------------------------------ #
    # Stage 3: Cache round-trip                                          #
    # ------------------------------------------------------------------ #

    def test_cache_stores_and_retrieves_issue_after_pipeline(self):
        """Integration: after processing, issue is persisted in cache and retrievable."""
        comic = _make_comic()
        self.cache.save_cached_issue("ComicVine", "4000-123456", comic)

        retrieved = self.cache.get_cached_issue("ComicVine", "4000-123456")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.series, "Batman")
        self.assertEqual(retrieved.number, "1")

    # ------------------------------------------------------------------ #
    # Stage 4: Processing state recorded                                 #
    # ------------------------------------------------------------------ #

    def test_processing_state_recorded_in_file_hashes(self):
        """Integration: mark_file_processed updates the file_hashes table."""
        cbz = _make_cbz(self.tmp, "Batman_001.cbz")
        comic = _make_comic()

        embed_comicinfo_in_cbz(cbz, comic)
        mark_file_processed(cbz, self.cache, provider_used="ComicVine")

        record = self.cache.get_file_record(cbz)
        self.assertIsNotNone(record)
        self.assertEqual(record["provider_used"], "ComicVine")
        self.assertEqual(record["status"], "SUCCESS")

    def test_complete_end_to_end_pipeline(self):
        """
        Integration: Full pipeline simulation — embed → verify → cache → state.
        All stages must succeed and be consistent.
        """
        cbz = _make_cbz(self.tmp, "Batman_Full_001.cbz")
        comic = _make_comic()

        # Stage 1: Embed
        embed_comicinfo_in_cbz(cbz, comic)

        # Stage 2: Verify
        verify_cbz_archive(cbz)

        # Stage 3: Cache issue
        self.cache.save_cached_issue("ComicVine", comic.provider_id, comic)

        # Stage 4: Record state
        mark_file_processed(cbz, self.cache, provider_used="ComicVine")

        # Assert: cache hit works
        cached = self.cache.get_cached_issue("ComicVine", comic.provider_id)
        self.assertEqual(cached.series, "Batman")

        # Assert: state recorded
        record = self.cache.get_file_record(cbz)
        self.assertEqual(record["status"], "SUCCESS")

        # Assert: file still valid
        self.assertTrue(zipfile.is_zipfile(cbz))
