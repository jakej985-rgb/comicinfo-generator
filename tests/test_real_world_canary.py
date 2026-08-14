"""
tests/test_real_world_canary.py — Phase 94: Real-World Canary Test

Simulates an authentic end-to-end canary library:
test-library/
├── Batman #001.cbz        (Case 2: Kapowarr match -> Kapowarr used, CV not queried)
├── Batman #002.cbz        (Case 3: Kapowarr unavailable -> ComicVine fallback)
├── Superman #001.cbz      (Case 6 & 7: Watcher debounce + Restart zero duplication)
├── SomeComic.cbr          (Case 5: CBR -> CBZ, ComicInfo embedded, CBR deleted)
├── ExistingMetadata.cbz   (Case 1: Existing ComicInfo -> zero provider calls)
└── AmbiguousComic.cbz     (Case 4: No match -> REVIEW, archive unchanged)
"""

import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from config import Config
from cache.db import CacheManager
from cache.jobs import JobStore
from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.resolver import MetadataResolver
from writers.archive import embed_comicinfo_in_cbz, verify_cbz_archive
from converters.cbr_to_cbz import convert_cbr_to_cbz
from automation.watcher import ComicFileEventHandler
from cache.tracker import mark_file_processed, is_file_unchanged


def _create_cbz(path: str, existing_comic: Comic = None) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("page_001.jpg", b"\xff\xd8\xff" + b"\x00" * 50)
        zf.writestr("page_002.jpg", b"\xff\xd8\xff" + b"\x00" * 50)
        if existing_comic:
            from writers.comicinfo import generate_xml_bytes
            zf.writestr("ComicInfo.xml", generate_xml_bytes(existing_comic))
    return path


def _create_dummy_cbr(path: str) -> str:
    """Creates a dummy CBR file with zip content for converter test."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("page_001.jpg", b"\xff\xd8\xff" + b"\x00" * 50)
    return path


class TestRealWorldCanary(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="canary_lib_")
        self.lib_dir = os.path.join(self.tmp_dir, "test-library")
        os.makedirs(self.lib_dir, exist_ok=True)

        self.cache_dir = os.path.join(self.tmp_dir, "cache")
        from config import KapowarrConfig, ComicvineConfig, CacheConfig
        self.config = Config(
            kapowarr=KapowarrConfig(url="http://localhost:5656", api_key="test-key"),
            comicvine=ComicvineConfig(api_key="test-cv-key"),
            cache=CacheConfig(db_path=os.path.join(self.cache_dir, "cache.db"))
        )
        self.cache_mgr = CacheManager(db_path=os.path.join(self.cache_dir, "cache.db"))
        self.job_store = JobStore(db_path=os.path.join(self.cache_dir, "jobs.db"))

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Case 1: Existing ComicInfo -> No unnecessary provider request      #
    # ------------------------------------------------------------------ #
    def test_case_1_existing_comicinfo_no_provider_query(self):
        """Case 1: Archive with complete valid ComicInfo.xml does not query external providers."""
        cbz_path = os.path.join(self.lib_dir, "Batman #001 (2016).cbz")
        existing = Comic(
            series="Batman",
            number="1",
            year=2016,
            publisher="DC Comics",
            web="https://comicvine.gamespot.com/batman-1/4000-1001/"
        )
        _create_cbz(cbz_path, existing_comic=existing)

        resolver = MetadataResolver(config=self.config, cache_mgr=self.cache_mgr)

        with patch.object(resolver.kapowarr, "search_issue") as mock_kap, \
             patch.object(resolver.comicvine, "search_issue") as mock_cv:
            identity, decision = resolver.resolve_identity(cbz_path)
            self.assertIsNotNone(identity)
            self.assertEqual(identity.series_name, "Batman")
            self.assertEqual(identity.issue_number, "1")
            # Providers must NEVER be called when existing metadata is complete and trusted
            mock_kap.assert_not_called()
            mock_cv.assert_not_called()

    # ------------------------------------------------------------------ #
    # Case 2: Kapowarr match -> Kapowarr used, ComicVine not queried     #
    # ------------------------------------------------------------------ #
    def test_case_2_kapowarr_preferred_over_comicvine(self):
        """Case 2: If Kapowarr matches with high confidence, ComicVine is not queried."""
        cbz_path = os.path.join(self.lib_dir, "Batman #001.cbz")
        _create_cbz(cbz_path)

        resolver = MetadataResolver(config=self.config, cache_mgr=self.cache_mgr)

        kap_candidate = ComicIdentity(
            series_name="Batman",
            issue_number="1",
            publication_year=2016,
            provider="Kapowarr",
            issue_id="kap-101"
        )

        with patch.object(resolver.kapowarr, "test_connection", return_value=True), \
             patch.object(resolver.kapowarr, "search_issue", return_value=[kap_candidate]), \
             patch.object(resolver.comicvine, "search_issue") as mock_cv_search:

            identity, decision = resolver.resolve_identity(cbz_path)
            self.assertIsNotNone(identity)
            self.assertEqual(identity.provider, "Kapowarr")
            self.assertEqual(identity.issue_id, "kap-101")
            # ComicVine must not be queried when Kapowarr provides a confident match
            mock_cv_search.assert_not_called()

    # ------------------------------------------------------------------ #
    # Case 3: Kapowarr unavailable -> ComicVine fallback                 #
    # ------------------------------------------------------------------ #
    def test_case_3_kapowarr_unavailable_comicvine_fallback(self):
        """Case 3: If Kapowarr is offline/returns error, pipeline cleanly falls back to ComicVine."""
        cbz_path = os.path.join(self.lib_dir, "Batman #002.cbz")
        _create_cbz(cbz_path)

        resolver = MetadataResolver(config=self.config, cache_mgr=self.cache_mgr)

        cv_candidate = ComicIdentity(
            series_name="Batman",
            issue_number="2",
            publication_year=2016,
            provider="ComicVine",
            issue_id="4000-1002"
        )

        with patch.object(resolver.kapowarr, "test_connection", return_value=False), \
             patch.object(resolver.comicvine, "search_issue", return_value=[cv_candidate]):

            identity, decision = resolver.resolve_identity(cbz_path)
            self.assertIsNotNone(identity)
            self.assertEqual(identity.provider, "ComicVine")
            self.assertEqual(identity.issue_id, "4000-1002")

    # ------------------------------------------------------------------ #
    # Case 4: No provider match -> REVIEW, archive unchanged             #
    # ------------------------------------------------------------------ #
    def test_case_4_no_provider_match_routes_to_review(self):
        """Case 4: No confident match -> MANUAL_REVIEW, archive is not modified."""
        cbz_path = os.path.join(self.lib_dir, "AmbiguousComic.cbz")
        _create_cbz(cbz_path)
        orig_size = os.path.getsize(cbz_path)

        resolver = MetadataResolver(config=self.config, cache_mgr=self.cache_mgr)

        with patch.object(resolver.kapowarr, "test_connection", return_value=True), \
             patch.object(resolver.kapowarr, "search_issue", return_value=[]), \
             patch.object(resolver.comicvine, "search_issue", return_value=[]):

            identity, decision = resolver.resolve_identity(cbz_path)
            self.assertIn(decision.level, ["MANUAL_REVIEW", "UNRESOLVED"])
            self.assertIn(decision.action, ["REVIEW", "SKIP"])

        # Original archive must remain unchanged
        self.assertEqual(os.path.getsize(cbz_path), orig_size)

    # ------------------------------------------------------------------ #
    # Case 5: CBR -> CBZ conversion workflow                             #
    # ------------------------------------------------------------------ #
    def test_case_5_cbr_to_cbz_conversion_and_embed(self):
        """Case 5: Converts CBR to CBZ, embeds ComicInfo.xml, and deletes source CBR."""
        cbr_path = os.path.join(self.lib_dir, "SomeComic.cbr")
        _create_dummy_cbr(cbr_path)
        cbz_target = os.path.join(self.lib_dir, "SomeComic.cbz")

        def mock_extractor_cmd(*args, **kwargs):
            # Extract dummy images to destination
            cmd = args[0]
            dest_dir = cmd[-1].rstrip("/")
            with zipfile.ZipFile(cbr_path, "r") as zf:
                zf.extractall(dest_dir)
            mock_res = MagicMock()
            mock_res.returncode = 0
            return mock_res

        with patch("converters.cbr_to_cbz.find_extractor", return_value=("unrar", "/usr/bin/unrar")), \
             patch("converters.cbr_to_cbz.subprocess.run", side_effect=mock_extractor_cmd):

            cbz_out = convert_cbr_to_cbz(cbr_path, delete_original=True)
            self.assertTrue(os.path.exists(cbz_out))
            self.assertFalse(os.path.exists(cbr_path))

            comic = Comic(series="Some Comic", number="1", year=2020)
            embed_comicinfo_in_cbz(cbz_out, comic)
            # verify_cbz_archive returns None on success (raises on failure)
            verify_cbz_archive(cbz_out)

    # ------------------------------------------------------------------ #
    # Case 6 & 7: Watcher single job cycle & Restart zero duplicate      #
    # ------------------------------------------------------------------ #
    def test_case_6_and_7_watcher_debounce_and_restart_safety(self):
        """Case 6 & 7: Watcher schedules exactly 1 job, and post-restart tracker prevents duplicate runs."""
        file_path = os.path.join(self.lib_dir, "Superman #001.cbz")
        _create_cbz(file_path)

        callback_calls = []
        def on_ready(path):
            callback_calls.append(path)

        handler = ComicFileEventHandler(
            cache_mgr=self.cache_mgr,
            on_file_changed=on_ready,
            stability_window=0.0,
            debounce_delay=0.0
        )

        class FakeEvent:
            is_directory = False
            src_path = file_path

        # Case 6: Fire create & modify events
        handler.on_created(FakeEvent())
        self.assertEqual(len(callback_calls), 1)

        # Mark processed in Hash Tracker
        mark_file_processed(file_path, self.cache_mgr, provider_used="ComicVine")

        # Case 7: Simulate process restart / re-scan
        # File is unchanged -> is_file_unchanged must return True
        self.assertTrue(is_file_unchanged(file_path, self.cache_mgr))

        # Firing event again after restart must be ignored
        handler.on_modified(FakeEvent())
        self.assertEqual(len(callback_calls), 1, "Duplicate job scheduled for already processed file!")


if __name__ == "__main__":
    unittest.main()
