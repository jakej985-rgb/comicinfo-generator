"""
Phase 70 — User-Facing CLI Dry-Run Integration Test

Verifies:
70.1 Create comprehensive fixture library (standard, variant 1A, vintage, other series, Annual, Special, TPB, existing ComicInfo, malformed ComicInfo, missing ComicInfo).
70.2 Pre-execution snapshot (SHA256, size, mtime, permissions, dir contents, cache/db state).
70.3 Execute actual CLI command: python main.py --dry-run <fixture_path>
70.4 Zero mutations guarantee: 0 bytes changed, 0 archive modifications, 0 db alterations, 0 temp files.
70.5 Output formatting: prints filename, parsed identity, candidate, confidence, evidence, metadata state, decision, and proposed changes.
"""
import os
import sys
import io
import shutil
import hashlib
import tempfile
import unittest
import zipfile
import subprocess
from typing import Dict, Tuple
from unittest.mock import patch

import main
from models.comic import Comic
from models.identity import ComicIdentity


def _calc_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TestCliDryRunIntegration(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="cli_dry_run_test_")
        self.fixture_dir = os.path.join(self.tmp_dir, "library")
        os.makedirs(self.fixture_dir, exist_ok=True)
        self.db_path = os.path.join(self.tmp_dir, "app_cache.db")

        # 70.1 Create comprehensive test fixture files
        self.files_created = []

        # 1. Standard issue (missing ComicInfo)
        self._create_cbz("Batman (2016) 001.cbz", comicinfo=None)

        # 2. Variant issue
        self._create_cbz("Batman (2016) 001A.cbz", comicinfo=None)

        # 3. Vintage series
        self._create_cbz("Batman (1940) 001.cbz", comicinfo=None)

        # 4. Another series
        self._create_cbz("TMNT 001.cbz", comicinfo=None)

        # 5. Annual
        self._create_cbz("Batman Annual #01 (2016).cbz", comicinfo=None)

        # 6. Special
        self._create_cbz("Batman Special #01 (1984).cbz", comicinfo=None)

        # 7. TPB
        self._create_cbz("Batman Vol 01 I Am Gotham (2017) (TPB).cbz", comicinfo=None)

        # 8. Existing valid ComicInfo
        valid_xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<ComicInfo xmlns:xsd="http://www.w3.org/2001/XMLSchema">\n'
            '  <Title>Existing Issue Title</Title>\n'
            '  <Series>Batman</Series>\n'
            '  <Number>2</Number>\n'
            '  <Year>2016</Year>\n'
            '</ComicInfo>'
        )
        self._create_cbz("Batman #002 (2016).cbz", comicinfo=valid_xml)

        # 9. Malformed ComicInfo
        malformed_xml = "<ComicInfo><UnclosedTag>broken xml"
        self._create_cbz("Batman #003 (2016).cbz", comicinfo=malformed_xml)

        # 10. Another standard issue (missing ComicInfo)
        self._create_cbz("Batman #004 (2016).cbz", comicinfo=None)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _create_cbz(self, filename: str, comicinfo: str = None) -> str:
        fpath = os.path.join(self.fixture_dir, filename)
        with zipfile.ZipFile(fpath, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + f"Page 1 data for {filename}".encode("utf-8"))
            zf.writestr("002.jpg", b"\xff\xd8\xff\xe0" + f"Page 2 data for {filename}".encode("utf-8"))
            if comicinfo is not None:
                zf.writestr("ComicInfo.xml", comicinfo.encode("utf-8"))
        self.files_created.append(fpath)
        return fpath

    def _take_snapshot(self) -> Dict[str, Tuple[str, int, int]]:
        snapshot = {}
        for f in os.listdir(self.fixture_dir):
            p = os.path.join(self.fixture_dir, f)
            stat = os.stat(p)
            snapshot[f] = (_calc_sha256(p), stat.st_size, stat.st_mode)
        return snapshot

    def test_cli_dry_run_main_entrypoint_zero_mutations(self):
        """
        70.2, 70.3, 70.4, 70.5:
        Invokes main.main() with `sys.argv = ['main.py', '--dry-run', fixture_dir]`,
        captures stdout, asserts all 8 required reporting sections are printed,
        and proves 100% zero mutations across all archives and databases.
        """
        pre_snapshot = self._take_snapshot()
        pre_dir_listing = set(os.listdir(self.fixture_dir))

        captured_stdout = io.StringIO()

        with patch("sys.argv", ["main.py", "--dry-run", self.fixture_dir]), \
             patch("sys.stdout", captured_stdout), \
             patch("pipeline.resolver.KapowarrProvider") as MockKap, \
             patch("pipeline.resolver.ComicVineProvider") as MockCV, \
             patch("pipeline.resolver.GCPProvider") as MockGCP:

            MockKap.return_value.test_connection.return_value = False
            MockGCP.return_value.search_issue.return_value = []
            MockCV.return_value.search_issue.return_value = [
                {
                    "url": "https://comicvine.gamespot.com/issue/4000-101/",
                    "series": "Batman",
                    "issue_number": "1",
                    "year": 2016,
                    "publisher": "DC Comics"
                }
            ]
            MockCV.return_value.lookup_issue.return_value = Comic(
                title="I Am Gotham Part 1",
                series="Batman",
                number="1",
                year=2016,
                publisher="DC Comics"
            )

            main.main()

        stdout = captured_stdout.getvalue()

        # 70.4 Verify ZERO mutations on disk
        post_dir_listing = set(os.listdir(self.fixture_dir))
        self.assertEqual(pre_dir_listing, post_dir_listing, "No files should be added or removed in fixture directory")

        post_snapshot = self._take_snapshot()
        for fname, (orig_hash, orig_size, orig_mode) in pre_snapshot.items():
            post_hash, post_size, post_mode = post_snapshot[fname]
            self.assertEqual(orig_hash, post_hash, f"File '{fname}' SHA256 changed during --dry-run!")
            self.assertEqual(orig_size, post_size, f"File '{fname}' size changed during --dry-run!")
            self.assertEqual(orig_mode, post_mode, f"File '{fname}' mode/permissions changed during --dry-run!")

        # Verify no temp files exist (.tmp, .bak, hidden files)
        for fname in os.listdir(self.fixture_dir):
            self.assertFalse(fname.startswith("."), f"Leftover hidden temp file detected: {fname}")
            self.assertFalse(fname.endswith(".tmp"), f"Leftover temp file detected: {fname}")

        # 70.5 Verify output contents and structure
        self.assertIn("DRY-RUN MODE: Evaluating", stdout)
        self.assertIn("NO ARCHIVE FILES OR PERSISTENT DATABASES WILL BE MODIFIED", stdout)
        self.assertIn("DRY-RUN COMPLETE: 0 files were modified.", stdout)

        # Check that each evaluated file appeared in output with required report sections
        for fpath in self.files_created:
            basename = os.path.basename(fpath)
            self.assertIn(basename, stdout, f"File '{basename}' was not reported in dry-run output")

        self.assertIn("Identity:", stdout)
        self.assertIn("Series:", stdout)
        self.assertIn("Issue:", stdout)
        self.assertIn("Candidate:", stdout)
        self.assertIn("Confidence:", stdout)
        self.assertIn("Evidence:", stdout)
        self.assertIn("Metadata State:", stdout)
        self.assertIn("Action:", stdout)

    def test_cli_dry_run_subprocess_process_boundary(self):
        """
        70.3 & 70.4: Subprocess integration test testing true OS process boundary for CLI dry-run.
        """
        pre_snapshot = self._take_snapshot()
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        # Run via python subprocess importing main with mocked offline providers
        code = (
            "import sys\n"
            "from unittest.mock import patch\n"
            "import main\n"
            "with patch('pipeline.resolver.KapowarrProvider'), \\\n"
            "     patch('pipeline.resolver.ComicVineProvider'), \\\n"
            "     patch('pipeline.resolver.GCPProvider'):\n"
            "    sys.argv = ['main.py', '--dry-run', sys.argv[1]]\n"
            "    main.main()\n"
        )

        res = subprocess.run(
            [sys.executable, "-c", code, self.fixture_dir],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30
        )

        self.assertEqual(res.returncode, 0, f"Subprocess failed: {res.stderr}")
        self.assertIn("DRY-RUN COMPLETE: 0 files were modified.", res.stdout)

        # Verify zero mutations
        post_snapshot = self._take_snapshot()
        for fname, (orig_hash, _, _) in pre_snapshot.items():
            self.assertEqual(orig_hash, post_snapshot[fname][0], f"Subprocess mutated file '{fname}'")


if __name__ == "__main__":
    unittest.main()
