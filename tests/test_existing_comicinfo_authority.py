"""
Phase 45 — Existing ComicInfo.xml Authority Tests (Sections 45.1 - 45.5)

Tests:
1. Valid XML classification & resolution
2. Partial XML classification
3. Malformed XML handling without crashes
4. XML agreeing with filename
5. XML conflicting with filename -> STATE_CONFLICTING & MANUAL_REVIEW
6. XML agreeing with Kapowarr
7. XML conflicting with Kapowarr
8. Unknown XML fields preserved losslessly
9. Overwrite enabled
10. Overwrite disabled
"""
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from lxml import etree

from config import Config
from cache.db import CacheManager
from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.existing_metadata import (
    inspect_existing_comicinfo,
    STATE_MISSING,
    STATE_VALID,
    STATE_PARTIAL,
    STATE_MALFORMED,
    STATE_CONFLICTING
)
from pipeline.filename_parser import parse_filename_identity
from pipeline.confidence import LEVEL_AUTO_ACCEPT, LEVEL_MANUAL_REVIEW, LEVEL_UNRESOLVED
from pipeline.resolver import MetadataResolver
from writers.comicinfo import ComicInfoWriter, ComicInfoParser


class TestExistingComicInfoAuthority(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "authority_cache.db")
        self.config = Config()
        self.config.cache.db_path = self.db_path
        self.cache = CacheManager(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_cbz(self, name: str, xml_bytes: bytes = None, comic: Comic = None) -> str:
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff" + b"\x00" * 32)
            if xml_bytes is not None:
                zf.writestr("ComicInfo.xml", xml_bytes)
            elif comic is not None:
                zf.writestr("ComicInfo.xml", ComicInfoWriter.generate_xml_bytes(comic))
        return path

    # 45.5.1: Valid XML
    def test_valid_xml_classification(self):
        comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")
        cbz = self._make_cbz("Batman #001 (2016).cbz", comic=comic)
        parsed = parse_filename_identity(cbz)

        report = inspect_existing_comicinfo(cbz, parsed=parsed)
        self.assertEqual(report.state, STATE_VALID)
        self.assertIsNotNone(report.candidate_identity)
        self.assertEqual(report.candidate_identity.series_name, "Batman")
        self.assertEqual(report.candidate_identity.issue_number, "1")
        self.assertEqual(report.candidate_identity.publication_year, 2016)

    # 45.5.2: Partial XML
    def test_partial_xml_classification(self):
        # Missing issue number
        comic = Comic(series="Batman", year=2016)
        cbz = self._make_cbz("Batman #001 (2016).cbz", comic=comic)
        parsed = parse_filename_identity(cbz)

        report = inspect_existing_comicinfo(cbz, parsed=parsed)
        self.assertEqual(report.state, STATE_PARTIAL)
        self.assertIsNotNone(report.candidate_identity)
        self.assertEqual(report.candidate_identity.series_name, "Batman")
        self.assertEqual(report.candidate_identity.issue_number, "")

    # 45.5.3: Malformed XML
    def test_malformed_xml_handling(self):
        bad_xml = b"<ComicInfo><Series>Batman<Number>UnclosedTag"
        cbz = self._make_cbz("Batman #001 (2016).cbz", xml_bytes=bad_xml)
        parsed = parse_filename_identity(cbz)

        report = inspect_existing_comicinfo(cbz, parsed=parsed)
        self.assertEqual(report.state, STATE_MALFORMED)
        self.assertIsNone(report.comic)
        self.assertTrue(len(report.error_message) > 0)

    # 45.5.4: XML Agreeing with Filename
    def test_xml_agreeing_with_filename(self):
        comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")
        cbz = self._make_cbz("Batman (2016)/Batman #001 (2016).cbz", comic=comic)

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = False
            MockCV.return_value.search_issue.return_value = []

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity(cbz)

            self.assertIsNotNone(identity)
            self.assertEqual(identity.series_name, "Batman")
            self.assertEqual(identity.issue_number, "1")
            self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)

    # 45.5.5: XML Conflicting with Filename
    def test_xml_conflicting_with_filename(self):
        # Filename specifies #1, but embedded XML contains #5
        comic = Comic(series="Batman", number="5", year=2016, publisher="DC Comics")
        cbz = self._make_cbz("Batman (2016)/Batman #001 (2016).cbz", comic=comic)
        parsed = parse_filename_identity(cbz)

        report = inspect_existing_comicinfo(cbz, parsed=parsed)
        self.assertEqual(report.state, STATE_CONFLICTING)
        self.assertTrue(any(c.type == "existing_xml_conflict" for c in report.conflicts))

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = False
            MockCV.return_value.search_issue.return_value = []

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity(cbz)

            # Contradictory XML must NOT be auto-accepted
            self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)
            self.assertEqual(decision.action, "REVIEW")

    # 45.5.6: XML Agreeing with Kapowarr
    def test_xml_agreeing_with_kapowarr(self):
        comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")
        cbz = self._make_cbz("Batman (2016)/Batman #001 (2016).cbz", comic=comic)

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.return_value = [
                {"id": 1001, "series": "Batman", "issue_number": "1", "year": 2016}
            ]
            MockCV.return_value.search_issue.return_value = []

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity(cbz)

            self.assertIsNotNone(identity)
            self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)

    # 45.5.7: XML Conflicting with Kapowarr
    def test_xml_conflicting_with_kapowarr(self):
        # XML says #1, but Kapowarr returns #2
        comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")
        cbz = self._make_cbz("Batman (2016)/Batman #001 (2016).cbz", comic=comic)

        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.return_value = [
                {"id": 1002, "series": "Batman", "issue_number": "2", "year": 2016}
            ]
            MockCV.return_value.search_issue.return_value = []

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity(cbz)

            self.assertNotEqual(decision.level, LEVEL_AUTO_ACCEPT)
            self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)

    # 45.5.8: Unknown XML fields preserved losslessly
    def test_unknown_xml_fields_preserved_losslessly(self):
        custom_xml = (
            b"<ComicInfo>"
            b"<Series>Batman</Series>"
            b"<Number>1</Number>"
            b"<Year>2016</Year>"
            b"<CustomPluginTag attr='xyz'>CustomValue</CustomPluginTag>"
            b"<KavitaSpecialReadingOrder>12345</KavitaSpecialReadingOrder>"
            b"</ComicInfo>"
        )
        parsed_comic = ComicInfoParser.parse_xml_bytes(custom_xml)
        self.assertIn("CustomPluginTag", parsed_comic.extra_fields)
        self.assertEqual(parsed_comic.extra_fields["CustomPluginTag"], "CustomValue")
        self.assertIn("KavitaSpecialReadingOrder", parsed_comic.extra_fields)

        # Re-generate XML bytes and assert unknown tags are preserved
        out_bytes = ComicInfoWriter.generate_xml_bytes(parsed_comic)
        re_parsed = ComicInfoParser.parse_xml_bytes(out_bytes)
        self.assertIn("CustomPluginTag", re_parsed.extra_fields)
        self.assertEqual(re_parsed.extra_fields["CustomPluginTag"], "CustomValue")
        self.assertEqual(re_parsed.extra_fields["KavitaSpecialReadingOrder"], "12345")

    # 45.5.9: Overwrite Enabled vs Disabled
    def test_overwrite_configuration_behavior(self):
        comic = Comic(series="OldSeries", number="1", year=1990)
        cbz = self._make_cbz("Batman (2016)/Batman #001 (2016).cbz", comic=comic)

        # Overwrite DISABLED: Existing conflicting metadata causes manual review
        self.config.output.overwrite = False
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = False
            MockCV.return_value.search_issue.return_value = []

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity(cbz)
            self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)

        # Overwrite ENABLED: Provider match for filename can overwrite
        self.config.output.overwrite = True
        with patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider"):
            MockKap.return_value.test_connection.return_value = True
            MockKap.return_value.search_issue.return_value = [
                {"id": 1001, "series": "Batman", "issue_number": "1", "year": 2016}
            ]
            MockCV.return_value.search_issue.return_value = []

            resolver = MetadataResolver(config=self.config, cache_mgr=self.cache)
            identity, decision = resolver.resolve_identity(cbz)
            self.assertEqual(identity.series_name, "Batman")
            self.assertEqual(identity.provider, "Kapowarr")


if __name__ == "__main__":
    unittest.main()
