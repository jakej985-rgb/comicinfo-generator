"""
Phase 42 — Architectural Invariants Tests

Explicit tests verifying each of the 8 core architectural invariants:
1. Identity Invariant: Filename alone is not proof of identity.
2. Provider Invariant: Providers return candidates, pipeline selects identity.
3. Metadata Invariant: Identity and metadata are separate.
4. Archive Safety Invariant: Never replace original with unverified archive.
5. Existing Metadata Invariant: Existing valid metadata is preserved/merged.
6. Automation Invariant: Every processing operation is restart-safe.
7. Error Classification Invariant: No match != provider failure.
8. Kapowarr Preference Invariant: Kapowarr preferred when associated & online.
"""
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.confidence import ConfidenceDecision
from pipeline.filename_parser import parse_filename_identity
from pipeline.resolver import MetadataResolver
from writers.archive import embed_comicinfo_in_cbz, verify_cbz_archive, ArchiveValidationError
from cache.db import CacheManager
from cache.jobs import JobStore


class TestArchitecturalInvariants(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test_cache.db")
        self.cache = CacheManager(db_path=self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_cbz(self, name: str) -> str:
        path = os.path.join(self.tmp, name)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff" + b"\x00" * 20)
        return path

    # 1. Identity Invariant: Filename alone is never sufficient proof of identity.
    def test_invariant_1_filename_alone_not_sufficient(self):
        parsed = parse_filename_identity("Batman 001.cbz")
        # Parser yields identity signals, not a final accepted Comic object
        self.assertEqual(parsed.series_name, "Batman")
        self.assertEqual(parsed.issue_number, "1")
        self.assertFalse(hasattr(parsed, "provider_id"))  # Not a resolved entity

    # 2. Provider Invariant: Providers return candidates, pipeline selects identity.
    def test_invariant_2_providers_return_candidates_not_decisions(self):
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = False
            MockCV.return_value.search_issue.return_value = [
                {"url": "https://comicvine.gamespot.com/issue/4000-111/", "title": "Batman #1"},
                {"url": "https://comicvine.gamespot.com/issue/4000-222/", "title": "Batman #1 Variant"}
            ]
            from config import Config
            cfg = Config()
            cfg.cache.db_path = self.db_path
            resolver = MetadataResolver(config=cfg, cache_mgr=self.cache)

            cbz = self._make_cbz("Batman_001.cbz")
            identity, decision = resolver.resolve_identity(cbz)
            # The resolver (pipeline) selected candidate & evaluated confidence, not CV
            self.assertIsNotNone(identity)
            self.assertIsInstance(decision, ConfidenceDecision)

    # 3. Metadata Invariant: Identity and metadata are separate concepts.
    def test_invariant_3_identity_and_metadata_are_separate(self):
        ident = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-123",
            series_name="Batman",
            issue_number="1"
        )
        comic = Comic(series="Batman", number="1", title="I Am Gotham")
        comic.identity = ident

        # ComicIdentity holds resolution identity signals
        self.assertEqual(ident.issue_id, "4000-123")
        # Comic holds metadata content
        self.assertEqual(comic.title, "I Am Gotham")
        self.assertEqual(comic.identity.issue_id, "4000-123")

    # 4. Archive Safety Invariant: Never replace original archive with unverified archive.
    def test_invariant_4_unverified_archive_never_replaces_original(self):
        cbz = self._make_cbz("Batman_safe.cbz")
        original_size = os.path.getsize(cbz)

        # Force verification failure on temporary file
        with patch("writers.archive.verify_cbz_archive", side_effect=ArchiveValidationError("Verification failed")):
            with self.assertRaises(ArchiveValidationError):
                embed_comicinfo_in_cbz(cbz, Comic(series="Batman"))

        # Original archive MUST remain untouched
        self.assertTrue(os.path.exists(cbz))
        self.assertEqual(os.path.getsize(cbz), original_size)

    # 5. Existing Metadata Invariant: Existing valid metadata is preserved.
    def test_invariant_5_existing_metadata_preserved_by_default(self):
        cbz = self._make_cbz("Batman_001.cbz")
        # Embed existing XML
        embed_comicinfo_in_cbz(cbz, Comic(series="Batman", number="1", publisher="DC Comics", summary="Original summary"))

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = False
            MockCV.return_value.search_issue.return_value = []

            from config import Config
            cfg = Config()
            cfg.output.overwrite = False
            cfg.cache.db_path = self.db_path
            resolver = MetadataResolver(config=cfg, cache_mgr=self.cache)

            comic, provider = resolver.resolve_file_metadata(cbz)
            self.assertIsNotNone(comic)
            self.assertEqual(provider, "ExistingXML")
            self.assertEqual(comic.summary, "Original summary")

    # 6. Automation Invariant: Every processing operation is restart-safe.
    def test_invariant_6_processing_restart_safe(self):
        cbz = self._make_cbz("Batman_001.cbz")
        job_db = os.path.join(self.tmp, "jobs.db")
        store = JobStore(db_path=job_db)

        # Create job and simulate worker claiming it (status -> PROCESSING)
        job = store.create_job(cbz)
        claimed = store.fetch_next_pending_job()
        self.assertEqual(claimed["status"], "PROCESSING")

        # Simulate crash restart recovery
        stuck_count = store.reset_stale_processing_jobs()
        self.assertEqual(stuck_count, 1)

        # Job is reset to PENDING and can be safely re-claimed
        reclaimed = store.fetch_next_pending_job()
        self.assertIsNotNone(reclaimed)
        self.assertEqual(reclaimed["id"], job["id"])
        self.assertEqual(reclaimed["status"], "PROCESSING")

    # 7. Error Classification Invariant: No match != provider failure.
    def test_invariant_7_no_match_is_not_provider_failure(self):
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = False
            # Provider returns empty results (no match)
            MockCV.return_value.search_issue.return_value = []

            from config import Config
            cfg = Config()
            cfg.cache.db_path = self.db_path
            resolver = MetadataResolver(config=cfg, cache_mgr=self.cache)

            cbz = self._make_cbz("UnknownComic_999.cbz")
            # Must return (None, decision) gracefully without raising exception
            identity, decision = resolver.resolve_identity(cbz)
            self.assertIsNone(identity)
            self.assertEqual(decision.action, "SKIP")

    # 8. Kapowarr Preference Invariant: Kapowarr preferred when associated & online.
    def test_invariant_8_kapowarr_preferred_when_online(self):
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"), \
             patch("pipeline.resolver.extract_identity_candidates") as mock_cands, \
             patch("pipeline.resolver.evaluate_confidence") as mock_conf:

            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.return_value = [
                {"id": "kap-100", "title": "Batman #1"}
            ]
            MockKap.return_value.lookup_issue.return_value = Comic(series="Batman", number="1", provider_name="Kapowarr")

            mock_cands.return_value = []
            mock_conf.return_value = ConfidenceDecision(score=98.0, action="AUTO_ACCEPT")

            from config import Config
            cfg = Config()
            cfg.cache.db_path = self.db_path
            resolver = MetadataResolver(config=cfg, cache_mgr=self.cache)

            cbz = self._make_cbz("Batman_001.cbz")
            comic, provider = resolver.resolve_file_metadata(cbz)

            self.assertIsNotNone(comic)
            self.assertEqual(provider, "Kapowarr")


    # 9. API Handler Invariant: Handlers route to services, never directly importing providers.
    def test_invariant_9_api_handlers_no_direct_provider_imports(self):
        import ast
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        handlers_path = os.path.join(repo_root, "api", "handlers.py")
        with open(handlers_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=handlers_path)

        violating_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("providers.") or alias.name == "providers":
                        violating_imports.append((node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                if node.module and (node.module.startswith("providers.") or node.module == "providers"):
                    violating_imports.append((node.lineno, node.module))

        self.assertEqual(
            len(violating_imports), 0,
            f"api/handlers.py violates boundary invariant by importing providers: {violating_imports}"
        )


if __name__ == "__main__":
    unittest.main()

