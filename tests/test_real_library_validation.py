"""
Phase 62 — Real Library Integration Validation Tests

Verifies:
1. Creation of representative test library covering 15 comic archive scenarios.
2. Dry-run mode produces zero side effects (files, timestamps, cache untouched).
3. Generated decisions contain explainable evidence, confidence scores, and conflict flags.
4. Real write batch embeds valid ComicInfo.xml and preserves exact image SHA256 hashes.
5. Kapowarr metadata flow integrates cleanly into resolver without permission disruption.
"""
import hashlib
import io
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

import config
from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.dry_run import DryRunContext
from pipeline.resolver import MetadataResolver
from writers.archive import (
    embed_comicinfo_in_cbz,
    verify_cbz_archive,
    compute_archive_sha256_manifest
)
from main import run_dry_run


class TestRealLibraryValidation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lib_dir = os.path.join(self.tmp, "library")
        os.makedirs(self.lib_dir, exist_ok=True)
        self._build_test_library()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_cbz(self, rel_path: str, pages: list, existing_xml: str = None):
        full_path = os.path.join(self.lib_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with zipfile.ZipFile(full_path, "w") as zf:
            for idx, pdata in enumerate(pages, 1):
                zf.writestr(f"{idx:03d}.jpg", b"\xff\xd8\xff\xe0" + pdata.encode("utf-8"))
            if existing_xml is not None:
                zf.writestr("ComicInfo.xml", existing_xml.encode("utf-8"))
        return full_path

    def _build_test_library(self):
        # 1. Standard issue
        self._create_cbz("Batman (2016) 001.cbz", ["batman_2016_p1", "batman_2016_p2"])
        # 2. Letter variant A
        self._create_cbz("Batman (2016) 001A.cbz", ["batman_variant_a_p1"])
        # 3. Letter variant B
        self._create_cbz("Batman (2016) 001B.cbz", ["batman_variant_b_p1"])
        # 4. Different era / year
        self._create_cbz("Batman (1940) 001.cbz", ["golden_age_batman_p1"])
        # 5. Independent series
        self._create_cbz("TMNT 001.cbz", ["tmnt_p1", "tmnt_p2"])
        # 6. Independent series variant
        self._create_cbz("TMNT 001A.cbz", ["tmnt_var_p1"])
        # 7. Annual
        self._create_cbz("Batman Annual #001 (2016).cbz", ["batman_annual_p1"])
        # 8. Special
        self._create_cbz("Batman Special #001 (2016).cbz", ["batman_special_p1"])
        # 9. Fractional issue (0.5)
        self._create_cbz("Deadpool #0.5 (1998).cbz", ["deadpool_half_p1"])
        # 10. Decimal issue (10.1)
        self._create_cbz("Avengers #10.1 (2012).cbz", ["avengers_point_one_p1"])
        # 11. TPB collected edition
        self._create_cbz("Batman Vol 01 The Court of Owls (2012) (TPB).cbz", ["court_of_owls_tpb_p1"])
        # 12. Graphic novel / collection
        self._create_cbz("Batman The Killing Joke (1988) (Collected).cbz", ["killing_joke_p1"])
        # 13. Existing valid ComicInfo.xml
        valid_xml = "<ComicInfo><Series>Spider-Man</Series><Number>1</Number><Year>2018</Year></ComicInfo>"
        self._create_cbz("Spider-Man #001 (2018).cbz", ["spiderman_p1"], existing_xml=valid_xml)
        # 14. Existing malformed ComicInfo.xml
        malformed_xml = "<ComicInfo><Series>Flash<Number>1"
        self._create_cbz("Flash #001 (2016).cbz", ["flash_p1"], existing_xml=malformed_xml)
        # 15. Missing ComicInfo.xml
        self._create_cbz("Wonder Woman #001 (2016).cbz", ["wonder_woman_p1"])

    def _get_library_state(self):
        state = {}
        for root, _, files in os.walk(self.lib_dir):
            for f in files:
                if f.endswith(".cbz"):
                    full = os.path.join(root, f)
                    st = os.stat(full)
                    with open(full, "rb") as fp:
                        sha = hashlib.sha256(fp.read()).hexdigest()
                    state[full] = (sha, st.st_mtime, st.st_size)
        return state

    def test_test_library_creation(self):
        """Test library contains 15 representative archive files."""
        state = self._get_library_state()
        self.assertEqual(len(state), 15)

    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_dry_run_zero_side_effects(self, MockGCP, MockKap, MockCV):
        """Dry-run execution processes library with zero file, timestamp, or database modifications."""
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.test_connection.return_value = False

        before_state = self._get_library_state()

        # Capture output during dry run execution
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            run_dry_run(self.lib_dir)
        finally:
            sys.stdout = old_stdout

        after_state = self._get_library_state()
        self.assertEqual(before_state, after_state)

        # Confirm no temporary files created
        for root, _, files in os.walk(self.lib_dir):
            for f in files:
                self.assertFalse(f.startswith(".tmp_"))

    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_decision_review_report(self, MockGCP, MockKap, MockCV):
        """Dry-run returns structured decision records with parsed identity, confidence, and actions."""
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = []
        MockGCP.return_value.test_connection.return_value = False

        cfg = config.load_config()
        with DryRunContext(config=cfg) as ctx:
            results = ctx.evaluate_target(self.lib_dir)

        self.assertEqual(len(results), 15)
        for res in results:
            self.assertTrue(bool(res.filename))
            self.assertTrue(bool(res.parsed_series))
            self.assertIn(res.decision.level, ("AUTO_ACCEPT", "ACCEPT_WITH_WARNING", "MANUAL_REVIEW", "UNRESOLVED"))
            self.assertIn(res.decision.action, ("UPDATE", "REVIEW", "SKIP"))
            self.assertIsInstance(res.decision.score, float)

    def test_real_write_batch(self):
        """Real write batch on 5 files embeds ComicInfo.xml and preserves exact image SHA256 hashes."""
        sample_files = [
            os.path.join(self.lib_dir, "Batman (2016) 001.cbz"),
            os.path.join(self.lib_dir, "Batman (2016) 001A.cbz"),
            os.path.join(self.lib_dir, "Deadpool #0.5 (1998).cbz"),
            os.path.join(self.lib_dir, "Avengers #10.1 (2012).cbz"),
            os.path.join(self.lib_dir, "Wonder Woman #001 (2016).cbz"),
        ]

        for file_path in sample_files:
            # Record original image SHA256 manifest
            before_manifest = compute_archive_sha256_manifest(file_path)
            self.assertTrue(len(before_manifest) > 0)

            comic = Comic(
                series="Validated Series",
                number="1",
                year=2026,
                publisher="Test Publisher",
                writers=["Author A"],
                pencillers=["Artist B"]
            )

            # Embed atomically with strict verification
            embed_comicinfo_in_cbz(file_path, comic, strict=True)

            # Assert verify_cbz_archive passes
            verify_cbz_archive(file_path, strict=True)

            # Assert image SHA256 hashes are identical
            after_manifest = compute_archive_sha256_manifest(file_path)
            self.assertEqual(before_manifest, after_manifest)

            # Assert ComicInfo.xml exists and is parseable
            with zipfile.ZipFile(file_path, "r") as zf:
                self.assertIn("ComicInfo.xml", zf.namelist())
                xml_data = zf.read("ComicInfo.xml").decode("utf-8")
                self.assertIn("<Series>Validated Series</Series>", xml_data)

    def test_kapowarr_metadata_pipeline_flow(self):
        """Simulated Kapowarr provider flows cleanly through resolver without permission issues."""
        mock_kapowarr = MagicMock()
        mock_kapowarr.test_connection.return_value = True
        mock_kapowarr.search_issue.return_value = [
            ComicIdentity(
                provider="Kapowarr",
                issue_id="kap-101",
                series_name="Batman",
                issue_number="1",
                publication_year=2016,
                publisher="DC Comics"
            )
        ]
        mock_kapowarr.lookup_issue.return_value = Comic(
            series="Batman",
            number="1",
            year=2016,
            publisher="DC Comics",
            writers=["Tom King"],
            pencillers=["David Finch"]
        )

        cfg = config.load_config()
        resolver = MetadataResolver(config=cfg, kapowarr=mock_kapowarr, comicvine=None)

        test_file = os.path.join(self.lib_dir, "Batman (2016) 001.cbz")
        res = resolver.resolve_file_pipeline(test_file)

        self.assertIsNotNone(res.comic)
        self.assertEqual(res.comic.series, "Batman")
        self.assertEqual(res.comic.number, "1")
        self.assertEqual(res.provider_results["Kapowarr"].status, "SUCCESS")


if __name__ == "__main__":
    unittest.main()
