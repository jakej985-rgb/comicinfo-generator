import os
import tempfile
import unittest
import zipfile
from models.comic import Comic
from writers.archive import (
    embed_comicinfo_in_cbz,
    verify_cbz_archive,
    ArchiveReadError,
    ArchiveWriteError,
    ArchiveValidationError
)

class TestArchiveSafety(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cbz_path = os.path.join(self.temp_dir.name, "test_comic.cbz")

        # Create a valid test CBZ with a dummy page image
        with zipfile.ZipFile(self.cbz_path, "w") as z:
            z.writestr("page_001.jpg", b"fake_image_bytes")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_embed_comicinfo_valid_cbz(self):
        comic = Comic(title="Test Title", series="Test Series", number="1", publisher="Test Publisher")
        result_path = embed_comicinfo_in_cbz(self.cbz_path, comic)
        self.assertEqual(result_path, self.cbz_path)

        # Verify archive contains ComicInfo.xml
        with zipfile.ZipFile(self.cbz_path, "r") as z:
            namelist = [n.lower() for n in z.namelist()]
            self.assertIn("comicinfo.xml", namelist)
            self.assertIn("page_001.jpg", namelist)

    def test_archive_verification_success(self):
        comic = Comic(title="Verification Test", series="Test Series", number="2")
        embed_comicinfo_in_cbz(self.cbz_path, comic)
        # Verify function does not raise
        verify_cbz_archive(self.cbz_path)

    def test_invalid_file_raises_read_error(self):
        non_existent = os.path.join(self.temp_dir.name, "non_existent.cbz")
        with self.assertRaises(ArchiveReadError):
            embed_comicinfo_in_cbz(non_existent, Comic())

    def test_cbr_file_raises_read_error(self):
        cbr_path = os.path.join(self.temp_dir.name, "test_comic.cbr")
        with open(cbr_path, "wb") as f:
            f.write(b"fake rar bytes")
        with self.assertRaises(ArchiveReadError):
            embed_comicinfo_in_cbz(cbr_path, Comic())

if __name__ == "__main__":
    unittest.main()
