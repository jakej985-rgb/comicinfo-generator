import os
import io
import sys
import unittest
import tempfile
import zipfile
from main import run_dry_run

class TestDryRunMode(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cbz_path = os.path.join(self.temp_dir, "Batman (2016) 001.cbz")

        with zipfile.ZipFile(self.cbz_path, "w") as z:
            z.writestr("page_001.jpg", b"fake_jpg_data")

        self.initial_size = os.path.getsize(self.cbz_path)

    def tearDown(self):
        if os.path.exists(self.cbz_path):
            os.remove(self.cbz_path)
        os.rmdir(self.temp_dir)

    def test_dry_run_never_modifies_archive(self):
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            run_dry_run(self.cbz_path)
        finally:
            sys.stdout = sys.__stdout__

        out = captured_output.getvalue()

        # 1. Verify dry-run output formatting
        self.assertIn("DRY-RUN MODE", out)
        self.assertIn("Archive:", out)
        self.assertIn("Batman (2016) 001.cbz", out)
        self.assertIn("0 files were modified", out)

        # 2. Verify archive file on disk was NOT touched or modified
        self.assertEqual(os.path.getsize(self.cbz_path), self.initial_size)
        with zipfile.ZipFile(self.cbz_path, "r") as z:
            self.assertNotIn("comicinfo.xml", [n.lower() for n in z.namelist()])

if __name__ == "__main__":
    unittest.main()
