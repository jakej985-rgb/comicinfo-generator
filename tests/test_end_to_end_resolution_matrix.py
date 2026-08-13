"""
Phase 52 — End-to-End Resolution Matrix Tests (Cases A through O)

Tests:
Case A: Filename only
Case B: Filename + ComicVine
Case C: Filename + GCD
Case D: Filename + Kapowarr
Case E: Filename + Kapowarr + ComicVine (Provider Agreement Bonus)
Case F: Filename + existing ComicInfo
Case G: Filename + conflicting ComicInfo
Case H: Provider unavailable
Case I: Provider returns no match
Case J: Multiple plausible matches (Score Margin Protection)
Case K: Variant / alternate cover
Case L: Annual
Case M: 0.5
Case N: 1A
Case O: Special

Rule: No issue number logic may use int(issue_number).
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
from pipeline.resolver import MetadataResolver
from pipeline.filename_parser import parse_filename_identity
from pipeline.issue_order import parse_issue_order
from pipeline.confidence import (
    LEVEL_AUTO_ACCEPT, LEVEL_MANUAL_REVIEW, LEVEL_UNRESOLVED
)
from pipeline.existing_metadata import inspect_existing_comicinfo, STATE_VALID, STATE_CONFLICTING
from observability.retry import (
    PROVIDER_STATE_SERVER_ERROR, PROVIDER_STATE_NOT_FOUND,
    ProviderUnavailable
)


class TestEndToEndResolutionMatrix(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "matrix_test.db")
        self.cache = CacheManager(db_path=self.db_path)
        self.cfg = config.load_config()
        self.cfg.cache.db_path = self.db_path

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_cbz(self, name: str, comicinfo_xml: str = "") -> str:
        cbz_path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(cbz_path), exist_ok=True)
        with zipfile.ZipFile(cbz_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"page1")
            if comicinfo_xml:
                zf.writestr("ComicInfo.xml", comicinfo_xml.encode("utf-8"))
        return cbz_path

    # Case A: Filename only (all external providers offline / empty; filename parsed, resolver safely skips without auto-accepting)
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_a_filename_only(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.search_issue.return_value = []

        parsed = parse_filename_identity("Batman #001 (2016).cbz")
        self.assertEqual(parsed.series_name, "Batman")
        self.assertEqual(parsed.issue_number, "1")
        self.assertEqual(parsed.year, 2016)

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("Batman #001 (2016).cbz")

        identity, decision = resolver.resolve_identity(cbz)
        # Invariant: Filename alone is not proof of identity without external corroboration
        self.assertIsNone(identity)
        self.assertEqual(decision.action, "SKIP")

    # Case B: Filename + ComicVine
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_b_filename_plus_comicvine(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockGCP.return_value.search_issue.return_value = []
        MockCV.return_value.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        MockCV.return_value.lookup_issue.return_value = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("Batman #001 (2016).cbz")

        identity, decision = resolver.resolve_identity(cbz)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "ComicVine")
        self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)
        self.assertEqual(decision.action, "UPDATE")

    # Case C: Filename + GCD
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_c_filename_plus_gcd(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.search_issue.return_value = [
            {"url": "https://www.comics.org/issue/2001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        MockGCP.return_value.lookup_issue.return_value = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("Batman #001 (2016).cbz")

        identity, decision = resolver.resolve_identity(cbz)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "GCP")
        self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)

    # Case D: Filename + Kapowarr
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_d_filename_plus_kapowarr(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = True
        MockKap.return_value.search_issue.return_value = [
            {"id": "kap-555", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        MockKap.return_value.lookup_issue.return_value = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.search_issue.return_value = []

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("Batman #001 (2016).cbz")

        identity, decision = resolver.resolve_identity(cbz)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "Kapowarr")
        self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)

    # Case E: Filename + Kapowarr + ComicVine (Agreement Bonus)
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_e_filename_plus_kapowarr_plus_comicvine(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = True
        MockKap.return_value.search_issue.return_value = [
            {"id": "kap-555", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        MockCV.return_value.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("Batman #001 (2016).cbz")

        identity, decision = resolver.resolve_identity(cbz)
        self.assertIsNotNone(identity)
        self.assertGreaterEqual(decision.score, 90.0)
        self.assertGreaterEqual(decision.provider_agreement_count, 2)

    # Case F: Filename + existing ComicInfo
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_f_filename_plus_existing_comicinfo(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.search_issue.return_value = []

        xml = """<?xml version="1.0"?>
        <ComicInfo>
            <Series>Batman</Series>
            <Number>1</Number>
            <Year>2016</Year>
            <Publisher>DC Comics</Publisher>
        </ComicInfo>"""
        cbz = self._create_cbz("Batman #001 (2016).cbz", comicinfo_xml=xml)

        report = inspect_existing_comicinfo(cbz)
        self.assertEqual(report.state, STATE_VALID)
        self.assertIsNotNone(report.comic)
        self.assertEqual(report.comic.series, "Batman")

    # Case G: Filename + conflicting ComicInfo
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_g_filename_plus_conflicting_comicinfo(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        # XML claims it's Superman #50
        xml = """<?xml version="1.0"?>
        <ComicInfo>
            <Series>Superman</Series>
            <Number>50</Number>
            <Year>1990</Year>
        </ComicInfo>"""
        cbz = self._create_cbz("Batman #001 (2016).cbz", comicinfo_xml=xml)

        report = inspect_existing_comicinfo(cbz, parsed=parse_filename_identity(cbz))
        self.assertEqual(report.state, STATE_CONFLICTING)

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        identity, decision = resolver.resolve_identity(cbz)
        self.assertIsNotNone(identity)
        # Correctly prefers Batman candidate over corrupt/conflicting XML
        self.assertEqual(identity.series_name, "Batman")

    # Case H: Provider unavailable (500 / timeout) -> Fallback to next provider
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_h_provider_unavailable_fallback(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        # ComicVine fails with ProviderUnavailable (HTTP 500)
        MockCV.return_value.search_issue.side_effect = ProviderUnavailable("HTTP 500 Server Error")
        # GCP is available and succeeds
        MockGCP.return_value.search_issue.return_value = [
            {"url": "https://www.comics.org/issue/2001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("Batman #001 (2016).cbz")

        identity, decision = resolver.resolve_identity(cbz)
        self.assertIsNotNone(identity)
        self.assertEqual(identity.provider, "GCP")

    # Case I: Provider returns no match
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_i_provider_returns_no_match(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.search_issue.return_value = []

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("CompletelyUnknownComic_xyz123.cbz")

        identity, decision = resolver.resolve_identity(cbz)
        self.assertEqual(decision.action, "SKIP")

    # Case J: Multiple plausible matches (Score Margin Protection)
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_case_j_multiple_plausible_matches_triggers_review(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockGCP.return_value.search_issue.return_value = []
        # Two distinct candidates with close scores (margin = 5.0 < 10.0)
        MockCV.return_value.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"},
            {"url": "https://comicvine.gamespot.com/issue/4000-2002/", "series": "Batman (2011)", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]

        resolver = MetadataResolver(config=self.cfg, cache_mgr=self.cache)
        cbz = self._create_cbz("Batman #001 (2016).cbz")

        identity, decision = resolver.resolve_identity(cbz)
        # Margin protection prevents automatic acceptance when candidates are closely matched
        self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)
        self.assertEqual(decision.action, "REVIEW")

    # Case K: Variant / alternate cover
    def test_case_k_variant_alternate_cover(self):
        parsed = parse_filename_identity("Batman #001 (2016) (Cover B Variant).cbz")
        self.assertEqual(parsed.series_name, "Batman")
        self.assertEqual(parsed.issue_number, "1")
        self.assertEqual(parsed.year, 2016)

    # Case L: Annual
    def test_case_l_annual_issue(self):
        parsed = parse_filename_identity("Batman Annual #01 (2016).cbz")
        self.assertIn("Batman", parsed.series_name)
        
        order = parse_issue_order("Annual 1")
        self.assertTrue(order.is_named or order.numeric_value >= 1000.0)

    # Case M: 0.5 fractional issue number
    def test_case_m_fractional_half_issue(self):
        parsed = parse_filename_identity("Batman #0.5 (2016).cbz")
        self.assertEqual(parsed.issue_number, "0.5")

        order = parse_issue_order("0.5")
        self.assertEqual(order.numeric_value, 0.5)

        # Ordering check without int()
        order_1 = parse_issue_order("1")
        self.assertLess(order, order_1)

    # Case N: 1A lettered variant number
    def test_case_n_lettered_variant(self):
        parsed = parse_filename_identity("Batman #1A (2016).cbz")
        self.assertEqual(parsed.issue_number, "1A")

        order_1a = parse_issue_order("1A")
        order_1b = parse_issue_order("1B")
        order_2 = parse_issue_order("2")

        self.assertEqual(order_1a.numeric_value, 1.0)
        self.assertEqual(order_1a.letter_suffix, "A")
        self.assertLess(order_1a, order_1b)
        self.assertLess(order_1b, order_2)

    # Case O: Special one-shot
    def test_case_o_special_oneshot(self):
        parsed = parse_filename_identity("Batman Special #1 (2016).cbz")
        self.assertIn("Batman", parsed.series_name)

        order_special = parse_issue_order("Special 1")
        self.assertTrue(order_special.numeric_value > 0)


if __name__ == "__main__":
    unittest.main()
