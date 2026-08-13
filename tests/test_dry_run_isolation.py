"""
Phase 50 — True Dry-Run Isolation Tests (Sections 50.1 - 50.3)

Tests:
1. Deep directory tree & file hash invariance before and after dry-run
2. Zero archive mutations and zero temp file creations
3. In-memory database isolation (no disk database creation or modification)
4. DryRunContext structure and evaluation output accuracy
"""
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

import config
from models.comic import Comic
from pipeline.dry_run import DryRunContext, DryRunResult
from cache.tracker import calculate_sha256
from main import run_dry_run


class TestDryRunIsolation(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.comics_dir = os.path.join(self.tmp, "comics")
        os.makedirs(self.comics_dir, exist_ok=True)

        # Create a few test comic archives
        self.cbz_path = os.path.join(self.comics_dir, "Batman #001 (2016).cbz")
        with zipfile.ZipFile(self.cbz_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"page1")
            zf.writestr("002.jpg", b"\xff\xd8\xff\xe0" + b"page2")

        self.cbr_path = os.path.join(self.comics_dir, "Superman #002 (2018).cbr")
        with open(self.cbr_path, "wb") as f:
            f.write(b"Rar!\x1a\x07\x00fake_cbr_stream")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _snapshot_directory(self, root_dir: str) -> dict:
        """Captures directory structure with relative paths, sizes, and SHA256 hashes."""
        snapshot = {}
        for root, dirs, files in os.walk(root_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, root_dir)
                stat = os.stat(full_path)
                sha = calculate_sha256(full_path)
                snapshot[rel_path] = {
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": sha
                }
        return snapshot

    # 50.1 & 50.3: Deep snapshot test verifying zero disk mutations
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_dry_run_zero_side_effect_isolation(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        MockCV.return_value.lookup_issue.return_value = Comic(
            series="Batman", number="1", year=2016, publisher="DC Comics"
        )

        # 1. Capture pre-run directory snapshot
        pre_snapshot = self._snapshot_directory(self.comics_dir)

        # 2. Run CLI dry-run across the directory
        run_dry_run(self.comics_dir)

        # 3. Capture post-run directory snapshot
        post_snapshot = self._snapshot_directory(self.comics_dir)

        # 4. Assert exact equality
        self.assertEqual(pre_snapshot, post_snapshot)
        for rel_path, meta in pre_snapshot.items():
            self.assertEqual(post_snapshot[rel_path]["sha256"], meta["sha256"])
            self.assertEqual(post_snapshot[rel_path]["size"], meta["size"])

        # 5. Assert no leftover .tmp files or .db files in the directory
        all_files = os.listdir(self.comics_dir)
        self.assertFalse(any(f.startswith(".tmp_") for f in all_files))
        self.assertFalse(any(f.endswith(".db") for f in all_files))

    # 50.2: DryRunContext evaluation output accuracy
    @patch("pipeline.resolver.ComicVineProvider")
    @patch("pipeline.resolver.KapowarrProvider")
    @patch("pipeline.resolver.GCPProvider")
    def test_dry_run_context_evaluation_accuracy(self, MockGCP, MockKap, MockCV):
        MockKap.return_value.test_connection.return_value = False
        MockCV.return_value.search_issue.return_value = [
            {"url": "https://comicvine.gamespot.com/issue/4000-1001/", "series": "Batman", "issue_number": "1", "year": 2016, "publisher": "DC Comics"}
        ]
        MockCV.return_value.lookup_issue.return_value = Comic(
            title="I Am Gotham", series="Batman", number="1", year=2016, publisher="DC Comics"
        )

        with DryRunContext() as ctx:
            results = ctx.evaluate_target(self.comics_dir)
            self.assertEqual(len(results), 2)
            
            batman_res = [r for r in results if "Batman" in r.filename][0]
            self.assertEqual(batman_res.parsed_series, "Batman")
            self.assertEqual(batman_res.parsed_issue, "1")
            self.assertEqual(batman_res.parsed_year, 2016)
            self.assertIsNotNone(batman_res.candidate)
            self.assertIn("Series", batman_res.fields_to_change)
            self.assertIn("Publisher", batman_res.fields_to_change)


if __name__ == "__main__":
    unittest.main()
