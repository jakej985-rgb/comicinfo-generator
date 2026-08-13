"""
Phase 44 — Identity Resolution Hardening Tests (Sections 44.1 - 44.7)

Verifies the central candidate decision policy:
1. Strong match with provider agreement bonus -> AUTO_ACCEPT
2. Close competing candidates (margin < 10.0) -> MANUAL_REVIEW
3. Wrong issue number -> NOT AUTO_ACCEPT (hard conflict)
4. Wrong series name -> REJECT / UNRESOLVED
5. Provider disagreement -> MANUAL_REVIEW
6. Existing XML conflict -> MANUAL_REVIEW / explicit conflict handling
"""
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

from config import Config
from cache.db import CacheManager
from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.confidence import (
    evaluate_confidence,
    evaluate_candidate_pool_decision,
    CandidateDecision,
    LEVEL_AUTO_ACCEPT,
    LEVEL_ACCEPT_WITH_WARNING,
    LEVEL_MANUAL_REVIEW,
    LEVEL_UNRESOLVED
)
from pipeline.filename_parser import parse_filename_identity
from pipeline.conflicts import detect_conflicts, detect_provider_disagreements, detect_existing_xml_conflicts, SEVERITY_FATAL, SEVERITY_ERROR
from pipeline.resolver import MetadataResolver
from writers.comicinfo import generate_xml_bytes


class TestIdentityResolutionHardening(unittest.TestCase):
    """
    Phase 44: Identity Resolution Hardening Unit Tests.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "hardening_cache.db")
        self.config = Config()
        self.config.cache.db_path = self.db_path
        self.cache = CacheManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_cbz(self, name: str, comic: Comic = None) -> str:
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff" + b"\x00" * 32)
            if comic:
                zf.writestr("ComicInfo.xml", generate_xml_bytes(comic))
        return path

    # 44.7.1: Strong match with provider agreement -> AUTO_ACCEPT
    def test_strong_match_with_provider_agreement(self):
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        cand_kap = ComicIdentity(
            provider="Kapowarr",
            issue_id="1001",
            series_name="Batman",
            issue_number="1",
            publication_year=2016,
            publisher="DC Comics"
        )
        cand_cv = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1001",
            series_name="Batman",
            issue_number="1",
            publication_year=2016,
            publisher="DC Comics"
        )

        best_cand, decision = evaluate_candidate_pool_decision(
            [cand_kap, cand_cv],
            parsed,
            min_margin=10.0
        )

        self.assertIsNotNone(best_cand)
        self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)
        self.assertEqual(decision.action, "UPDATE")
        # Assert provider agreement evidence is attached
        agreement_evidence = [e for e in decision.evidence if e.source == "ProviderAgreement"]
        self.assertTrue(len(agreement_evidence) > 0)
        self.assertIn("Kapowarr", agreement_evidence[0].actual)
        self.assertIn("ComicVine", agreement_evidence[0].actual)

    # 44.7.2: Close candidates (margin < 10.0) -> MANUAL_REVIEW
    def test_close_candidates_score_margin_protection(self):
        # Filename without year: both Batman (2011) #1 and Batman (2016) #1 are close candidates
        parsed = parse_filename_identity("Batman #001.cbz")
        # Candidate A: Batman (2016) #1
        cand_a = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1001",
            series_name="Batman",
            issue_number="1",
            publication_year=2016,
            publisher="DC Comics"
        )
        # Candidate B: Batman (2011) #1
        cand_b = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1002",
            series_name="Batman",
            issue_number="1",
            publication_year=2011,
            publisher="DC Comics"
        )

        best_cand, decision = evaluate_candidate_pool_decision(
            [cand_a, cand_b],
            parsed,
            min_margin=10.0
        )

        self.assertIsNotNone(best_cand)
        self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)
        self.assertEqual(decision.action, "REVIEW")
        self.assertTrue(decision.is_ambiguous_margin)
        self.assertIsNotNone(decision.score_margin)
        self.assertTrue(any("Ambiguous candidates: score margin" in r for r in decision.reasons))

    # 44.7.3: Wrong issue number -> NEVER AUTO_ACCEPT
    def test_wrong_issue_hard_conflict_not_auto_accept(self):
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        cand_wrong_num = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1002",
            series_name="Batman",
            issue_number="2", # Wrong issue
            publication_year=2016
        )

        conflicts = detect_conflicts(cand_wrong_num, parsed)
        self.assertTrue(any(c.type == "issue_conflict" and c.severity == SEVERITY_FATAL for c in conflicts))

        best_cand, decision = evaluate_candidate_pool_decision(
            [cand_wrong_num],
            parsed
        )

        self.assertNotEqual(decision.level, LEVEL_AUTO_ACCEPT)
        self.assertNotEqual(decision.level, LEVEL_ACCEPT_WITH_WARNING)
        self.assertTrue(decision.has_critical_conflict)

    # 44.7.4: Wrong series name -> REJECT / UNRESOLVED
    def test_wrong_series_hard_conflict_reject(self):
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        cand_wrong_series = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-2001",
            series_name="Superman", # Wrong series
            issue_number="1",
            publication_year=2016
        )

        conflicts = detect_conflicts(cand_wrong_series, parsed)
        self.assertTrue(any(c.type == "series_conflict" and c.severity == SEVERITY_FATAL for c in conflicts))

        best_cand, decision = evaluate_candidate_pool_decision(
            [cand_wrong_series],
            parsed
        )

        self.assertEqual(decision.level, LEVEL_UNRESOLVED)
        self.assertEqual(decision.action, "SKIP")

    # 44.7.5: Provider disagreement -> MANUAL_REVIEW
    def test_provider_disagreement_downgrades_to_review(self):
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        # Kapowarr returns Issue 1, ComicVine returns Issue 2 for same target
        cand_kap = ComicIdentity(
            provider="Kapowarr",
            issue_id="1001",
            series_name="Batman",
            issue_number="1"
        )
        cand_cv = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1002",
            series_name="Batman",
            issue_number="2"
        )

        disagreements = detect_provider_disagreements([cand_kap, cand_cv])
        self.assertTrue(len(disagreements) > 0)
        self.assertEqual(disagreements[0].type, "provider_disagreement")

        best_cand, decision = evaluate_candidate_pool_decision(
            [cand_kap, cand_cv],
            parsed
        )

        self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)
        self.assertEqual(decision.action, "REVIEW")
        self.assertTrue(any("Provider disagreement" in r for r in decision.reasons))

    # 44.7.6: Existing XML conflict -> explicit conflict handling & REVIEW
    def test_existing_xml_conflict_handling(self):
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        existing_comic = Comic(
            series="Batman",
            number="5", # Conflicting issue number 5 vs 1
            year=2016
        )

        xml_conflicts = detect_existing_xml_conflicts(parsed, existing_comic)
        self.assertTrue(len(xml_conflicts) > 0)
        self.assertEqual(xml_conflicts[0].type, "existing_xml_conflict")

        cand = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-1001",
            series_name="Batman",
            issue_number="1",
            publication_year=2016
        )

        best_cand, decision = evaluate_candidate_pool_decision(
            [cand],
            parsed,
            existing_comic=existing_comic
        )

        self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)
        self.assertEqual(decision.action, "REVIEW")
        self.assertTrue(decision.has_critical_conflict)
        self.assertTrue(any("Existing ComicInfo.xml conflict" in r for r in decision.reasons))

    def test_resolver_end_to_end_with_hardening(self):
        """End-to-end MetadataResolver resolution using CandidateDecision policy."""
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):

            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.return_value = [
                {"id": 1001, "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
            ]
            MockCV.return_value.search_issue.return_value = [
                {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
            ]

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            cbz = self._make_cbz("Batman (2016)/Batman #001 (2016).cbz")

            identity, decision = resolver.resolve_identity(cbz)
            self.assertIsNotNone(identity)
            self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)
            self.assertEqual(decision.action, "UPDATE")


if __name__ == "__main__":
    unittest.main()
