"""
Phase 58 — Formalize Identity Authority and Conflict Rules Tests

Verifies:
1. XML vs Filename conflict
2. XML vs Kapowarr conflict
3. XML vs ComicVine conflict
4. Embedded provider ID vs candidate provider ID conflict
5. Kapowarr vs ComicVine disagreement -> MANUAL_REVIEW
6. Multi-provider agreement (Kapowarr + ComicVine + GCD) -> AUTO_ACCEPT + bonus
7. Variant letter mismatch (#1 vs #1A)
8. Volume mismatch (Vol 1 vs Vol 2)
9. Year mismatch (1940 vs 2016)
"""
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import config
from models.comic import Comic
from models.identity import ComicIdentity
from cache.db import CacheManager
from pipeline.filename_parser import parse_filename_identity
from pipeline.confidence import (
    evaluate_candidate_pool_decision,
    LEVEL_AUTO_ACCEPT,
    LEVEL_MANUAL_REVIEW
)
from pipeline.conflicts import (
    detect_conflicts,
    detect_provider_disagreements,
    detect_existing_xml_conflicts,
    detect_xml_provider_conflicts,
    CONFLICT_XML_PROVIDER_ID,
    CONFLICT_PROVIDER_DISAGREEMENT,
    CONFLICT_VARIANT,
    CONFLICT_VOLUME,
    CONFLICT_YEAR
)
from pipeline.resolver import MetadataResolver


class TestIdentityAuthorityAndConflicts(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "auth_conf.db")
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

    def test_xml_vs_filename_conflict(self):
        """Existing XML issue #5 contradicts filename issue #1 -> conflict detected, REVIEW."""
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        existing_comic = Comic(series="Batman", number="5", year=2016)

        conflicts = detect_existing_xml_conflicts(parsed, existing_comic)
        self.assertTrue(len(conflicts) > 0)
        self.assertEqual(conflicts[0].type, "existing_xml_conflict")

    def test_xml_vs_provider_conflict(self):
        """Existing XML Batman (1940) #1 contradicts provider candidate Batman (2016) #1 -> REVIEW."""
        existing_comic = Comic(series="Batman", number="1", year=1940)
        cand = ComicIdentity(provider="ComicVine", issue_id="4000-1001", series_name="Batman", issue_number="1", publication_year=2016)

        conflicts = detect_xml_provider_conflicts(existing_comic, cand)
        self.assertTrue(any(c.type == "xml_provider_conflict" for c in conflicts))

    def test_embedded_provider_id_vs_candidate_id_conflict(self):
        """Existing XML provider_id='4000-123' vs candidate issue_id='4000-456' -> FATAL conflict."""
        existing_comic = Comic(series="Batman", number="1", year=2016, provider_id="4000-123")
        cand = ComicIdentity(provider="ComicVine", issue_id="4000-456", series_name="Batman", issue_number="1", publication_year=2016)

        conflicts = detect_xml_provider_conflicts(existing_comic, cand)
        fatal_conflicts = [c for c in conflicts if c.type == CONFLICT_XML_PROVIDER_ID]
        self.assertEqual(len(fatal_conflicts), 1)
        self.assertEqual(fatal_conflicts[0].severity, "FATAL")

    def test_kapowarr_vs_comicvine_disagreement(self):
        """Kapowarr returns Batman (2016) #1, ComicVine returns Batman (1940) #1 -> MANUAL_REVIEW."""
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        c1 = ComicIdentity(provider="Kapowarr", issue_id="kap-1", series_name="Batman", issue_number="1", publication_year=2016)
        c2 = ComicIdentity(provider="ComicVine", issue_id="4000-1", series_name="Batman", issue_number="1", publication_year=1940)

        disagreements = detect_provider_disagreements([c1, c2])
        self.assertTrue(len(disagreements) > 0)
        self.assertEqual(disagreements[0].type, CONFLICT_PROVIDER_DISAGREEMENT)

        cand, dec = evaluate_candidate_pool_decision([c1, c2], parsed)
        self.assertEqual(dec.level, LEVEL_MANUAL_REVIEW)
        self.assertEqual(dec.action, "REVIEW")

    def test_multi_provider_agreement_bonus(self):
        """Kapowarr + ComicVine + GCP all agree on Batman (2016) #1 -> AUTO_ACCEPT with agreement bonus."""
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        c1 = ComicIdentity(provider="Kapowarr", issue_id="kap-1", series_name="Batman", issue_number="1", publication_year=2016)
        c2 = ComicIdentity(provider="ComicVine", issue_id="4000-1", series_name="Batman", issue_number="1", publication_year=2016)
        c3 = ComicIdentity(provider="GCP", issue_id="gcp-1", series_name="Batman", issue_number="1", publication_year=2016)

        cand, dec = evaluate_candidate_pool_decision([c1, c2, c3], parsed)
        self.assertIsNotNone(cand)
        self.assertEqual(dec.level, LEVEL_AUTO_ACCEPT)
        self.assertEqual(dec.action, "UPDATE")
        self.assertGreaterEqual(dec.provider_agreement_count, 3)

    def test_variant_disagreement_handling(self):
        """Target issue is #1, candidate is variant #1A -> variant conflict detected."""
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        cand = ComicIdentity(provider="ComicVine", issue_id="4000-1A", series_name="Batman", issue_number="1A", publication_year=2016)

        conflicts = detect_conflicts(cand, parsed)
        var_conflicts = [c for c in conflicts if c.type == CONFLICT_VARIANT]
        self.assertEqual(len(var_conflicts), 1)

    def test_volume_disagreement_handling(self):
        """Target is Vol 1, candidate is Vol 2 -> volume conflict detected."""
        parsed = parse_filename_identity("Batman Vol 1 #001 (2016).cbz")
        cand = ComicIdentity(provider="ComicVine", issue_id="4000-1", series_name="Batman", issue_number="1", publication_year=2016)
        setattr(cand, "volume", "2")

        conflicts = detect_conflicts(cand, parsed)
        vol_conflicts = [c for c in conflicts if c.type == CONFLICT_VOLUME]
        self.assertEqual(len(vol_conflicts), 1)

    def test_year_disagreement_handling(self):
        """Target is 2016, candidate is 1940 -> year conflict FATAL."""
        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        cand = ComicIdentity(provider="ComicVine", issue_id="4000-1", series_name="Batman", issue_number="1", publication_year=1940)

        conflicts = detect_conflicts(cand, parsed)
        yr_conflicts = [c for c in conflicts if c.type == CONFLICT_YEAR]
        self.assertEqual(len(yr_conflicts), 1)
        self.assertEqual(yr_conflicts[0].severity, "FATAL")


if __name__ == "__main__":
    unittest.main()
