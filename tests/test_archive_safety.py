import os
import time
import zipfile
import tempfile
import unittest
from models.comic import Comic
from writers.archive import embed_comicinfo_in_cbz, verify_cbz_archive

class TestArchiveSafetyAndMetadata(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cbz_path = os.path.join(self.temp_dir, "sample.cbz")

        with zipfile.ZipFile(self.cbz_path, "w") as z:
            z.writestr("page_001.jpg", b"fake_jpg_content_data")

        # Set specific permissions and modification time
        os.chmod(self.cbz_path, 0o644)

    def tearDown(self):
        if os.path.exists(self.cbz_path):
            os.remove(self.cbz_path)
        os.rmdir(self.temp_dir)

    def test_atomic_archive_embedding(self):
        comic = Comic(series="Batman", number="1", year=2016)
        out_path = embed_comicinfo_in_cbz(self.cbz_path, comic)

        self.assertEqual(out_path, self.cbz_path)
        self.assertTrue(os.path.exists(self.cbz_path))
        verify_cbz_archive(self.cbz_path)

        with zipfile.ZipFile(self.cbz_path, "r") as z:
            names = [n.lower() for n in z.namelist()]
            self.assertIn("comicinfo.xml", names)
            self.assertIn("page_001.jpg", names)

    def test_preserve_file_permissions(self):
        comic = Comic(series="Batman", number="1")
        embed_comicinfo_in_cbz(self.cbz_path, comic)

        st = os.stat(self.cbz_path)
        mode = st.st_mode & 0o777
        self.assertEqual(mode, 0o644)

if __name__ == "__main__":
    unittest.main()
