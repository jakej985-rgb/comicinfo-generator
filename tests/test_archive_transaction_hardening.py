"""
Phase 47 — Archive Transaction Hardening Tests (Sections 47.1 - 47.6)

Tests:
1. Entry-by-entry CRC & size integrity verification
2. ZIP metadata & compression preservation
3. Directory durability fsync execution
4. Failure injection across all 8 stages of the archive transaction lifecycle:
   - Stage 1: Temp creation failure
   - Stage 2: Source ZIP read failure
   - Stage 3: ZIP write failure
   - Stage 4: XML generation failure
   - Stage 5: Pre-replacement verification failure (CRC mismatch / XML corruption)
   - Stage 6: fsync failure
   - Stage 7: os.replace atomic replace failure
   - Stage 8: Post-replacement verification failure
"""
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

from models.comic import Comic
from writers.archive import (
    embed_comicinfo_in_cbz,
    verify_cbz_archive,
    fsync_directory,
    ArchiveReadError,
    ArchiveWriteError,
    ArchiveValidationError
)


class TestArchiveTransactionHardening(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_sample_cbz(self, name: str = "test.cbz", page_count: int = 3) -> str:
        cbz_path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(cbz_path), exist_ok=True)
        with zipfile.ZipFile(cbz_path, "w") as zf:
            for i in range(1, page_count + 1):
                # Valid fake JPEG stream
                content = b"\xff\xd8\xff\xe0\x00\x10JFIF" + f"page_{i}_content".encode("utf-8")
                zf.writestr(f"page_{i:03d}.jpg", content, compress_type=zipfile.ZIP_DEFLATED)
        return cbz_path

    # 47.2 & 47.3: CRC verification & ZipInfo preservation
    def test_crc_manifest_verification_and_metadata_preservation(self):
        cbz_path = self._create_sample_cbz("batman_001.cbz")
        
        # Read initial CRCs
        with zipfile.ZipFile(cbz_path, "r") as zf:
            initial_manifest = {item.filename: (item.CRC, item.file_size) for item in zf.infolist()}

        comic = Comic(series="Batman", number="1", year=2016, publisher="DC Comics")
        embed_comicinfo_in_cbz(cbz_path, comic)

        # Assert post-embed CRCs for all original pages are 100% identical
        with zipfile.ZipFile(cbz_path, "r") as zf:
            post_manifest = {item.filename: (item.CRC, item.file_size) for item in zf.infolist()}
            for fname, (orig_crc, orig_size) in initial_manifest.items():
                self.assertIn(fname, post_manifest)
                self.assertEqual(post_manifest[fname][0], orig_crc)
                self.assertEqual(post_manifest[fname][1], orig_size)
            self.assertIn("ComicInfo.xml", post_manifest)

    # 47.2: CRC mismatch detection triggers ArchiveValidationError
    def test_crc_mismatch_detected_in_verification(self):
        cbz_path = self._create_sample_cbz("tampered.cbz")
        comic = Comic(series="Batman", number="1")
        embed_comicinfo_in_cbz(cbz_path, comic)

        # Forge manifest with incorrect expected CRC
        tampered_manifest = {"page_001.jpg": (999999, 100)}
        with self.assertRaises(ArchiveValidationError) as ctx:
            verify_cbz_archive(cbz_path, original_manifest=tampered_manifest)
        self.assertIn("Entry integrity mismatch", str(ctx.exception))

    # 47.5: Directory durability
    def test_fsync_directory_execution(self):
        dir_path = os.path.join(self.tmp, "comics_dir")
        os.makedirs(dir_path, exist_ok=True)
        # Should execute cleanly without raising unexpected exceptions
        fsync_directory(dir_path)

    # 47.6 Stage 1: Failure at temp file creation
    def test_failure_stage_1_temp_creation(self):
        cbz_path = self._create_sample_cbz("stage1.cbz")
        with open(cbz_path, "rb") as f:
            orig_bytes = f.read()

        comic = Comic(series="Batman", number="1")
        with patch("tempfile.NamedTemporaryFile", side_effect=OSError("Disk full or permission denied")):
            with self.assertRaises(ArchiveWriteError):
                embed_comicinfo_in_cbz(cbz_path, comic)

        # Original archive must be untouched
        with open(cbz_path, "rb") as f:
            self.assertEqual(f.read(), orig_bytes)

    # 47.6 Stage 2: Failure at source ZIP read
    def test_failure_stage_2_source_zip_read(self):
        bad_path = os.path.join(self.tmp, "not_a_zip.cbz")
        with open(bad_path, "wb") as f:
            f.write(b"NOT_A_VALID_ZIP_HEADER")

        comic = Comic(series="Batman", number="1")
        with self.assertRaises(ArchiveReadError):
            embed_comicinfo_in_cbz(bad_path, comic)

    # 47.6 Stage 3: Failure at ZIP write
    def test_failure_stage_3_zip_write(self):
        cbz_path = self._create_sample_cbz("stage3.cbz")
        with open(cbz_path, "rb") as f:
            orig_bytes = f.read()

        comic = Comic(series="Batman", number="1")
        with patch("zipfile.ZipFile.writestr", side_effect=IOError("Write failed midway")):
            with self.assertRaises(ArchiveWriteError):
                embed_comicinfo_in_cbz(cbz_path, comic)

        # Original archive untouched & no leftover .tmp files
        with open(cbz_path, "rb") as f:
            self.assertEqual(f.read(), orig_bytes)
        tmp_files = [f for f in os.listdir(self.tmp) if f.startswith(".tmp_")]
        self.assertEqual(len(tmp_files), 0)

    # 47.6 Stage 4: Failure at XML generation
    def test_failure_stage_4_xml_generation(self):
        cbz_path = self._create_sample_cbz("stage4.cbz")
        with open(cbz_path, "rb") as f:
            orig_bytes = f.read()

        with patch("writers.archive.generate_xml_bytes", side_effect=ValueError("XML generation error")):
            with self.assertRaises(ValueError):
                embed_comicinfo_in_cbz(cbz_path, Comic(series="Batman"))

        with open(cbz_path, "rb") as f:
            self.assertEqual(f.read(), orig_bytes)

    # 47.6 Stage 5: Failure at pre-replacement verification
    def test_failure_stage_5_pre_verification(self):
        cbz_path = self._create_sample_cbz("stage5.cbz")
        with open(cbz_path, "rb") as f:
            orig_bytes = f.read()

        # Simulate pre-verification detecting corrupt ComicInfo.xml
        with patch("writers.archive.verify_cbz_archive", side_effect=[
            ArchiveValidationError("Corrupt XML in temp archive", operation="verify_comicinfo"),
            None
        ]):
            with self.assertRaises(ArchiveValidationError):
                embed_comicinfo_in_cbz(cbz_path, Comic(series="Batman"))

        # Original archive untouched & no leftover .tmp files
        with open(cbz_path, "rb") as f:
            self.assertEqual(f.read(), orig_bytes)
        tmp_files = [f for f in os.listdir(self.tmp) if f.startswith(".tmp_")]
        self.assertEqual(len(tmp_files), 0)

    # 47.6 Stage 6: Failure at fsync
    def test_failure_stage_6_fsync_handling(self):
        cbz_path = self._create_sample_cbz("stage6.cbz")
        comic = Comic(series="Batman", number="1")
        
        # fsync failure does not break the transaction unless it raises uncaught OSError
        with patch("os.fsync", side_effect=OSError("Mock fsync failure")):
            updated = embed_comicinfo_in_cbz(cbz_path, comic)
            self.assertEqual(updated, cbz_path)
            self.assertTrue(os.path.exists(cbz_path))

    # 47.6 Stage 7: Failure at atomic replace
    def test_failure_stage_7_atomic_replace(self):
        cbz_path = self._create_sample_cbz("stage7.cbz")
        with open(cbz_path, "rb") as f:
            orig_bytes = f.read()

        comic = Comic(series="Batman", number="1")
        with patch("os.replace", side_effect=OSError("Simulated cross-device link or rename lock")):
            with self.assertRaises(ArchiveWriteError):
                embed_comicinfo_in_cbz(cbz_path, comic)

        # Original archive untouched & no leftover .tmp files
        with open(cbz_path, "rb") as f:
            self.assertEqual(f.read(), orig_bytes)
        tmp_files = [f for f in os.listdir(self.tmp) if f.startswith(".tmp_")]
        self.assertEqual(len(tmp_files), 0)

    # 47.6 Stage 8: Failure at post-replacement verification
    def test_failure_stage_8_post_verification(self):
        cbz_path = self._create_sample_cbz("stage8.cbz")
        comic = Comic(series="Batman", number="1")

        # Simulate pre-verification passing, but post-verification raising error
        with patch("writers.archive.verify_cbz_archive", side_effect=[
            None, # Pre-verification passes
            ArchiveValidationError("Post-replacement inspection failed", operation="verify_cbz") # Post fails
        ]):
            with self.assertRaises(ArchiveValidationError):
                embed_comicinfo_in_cbz(cbz_path, comic)


if __name__ == "__main__":
    unittest.main()
