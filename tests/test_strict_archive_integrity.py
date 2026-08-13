"""
Phase 60 — Strict Archive Integrity Mode Tests

Verifies:
1. compute_archive_sha256_manifest returns accurate hash mapping for all non-ComicInfo files.
2. Complex archive with multiple images, nested directories, text files, unusual filenames,
   and existing ComicInfo.xml preserves identical SHA256 hashes for all untouched entries
   before and after atomic replacement under strict verification mode.
3. Injected modification or corruption of an untouched entry raises ArchiveValidationError in strict mode.
"""
import hashlib
import os
import shutil
import tempfile
import unittest
import zipfile

from models.comic import Comic
from writers.archive import (
    embed_comicinfo_in_cbz,
    verify_cbz_archive,
    compute_archive_sha256_manifest,
    ArchiveValidationError
)


class TestStrictArchiveIntegrity(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_complex_archive(self, name: str) -> str:
        cbz_path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(cbz_path), exist_ok=True)
        with zipfile.ZipFile(cbz_path, "w") as zf:
            # 1. Multiple images
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"image_page_1_data_12345")
            zf.writestr("002.png", b"\x89PNG\r\n\x1a\n" + b"image_page_2_data_67890")
            # 2. Nested directory images
            zf.writestr("scans/chapter1/003.webp", b"RIFF....WEBP" + b"nested_image_data")
            # 3. Text files
            zf.writestr("notes.txt", b"Scanned by ReleaseGroup 2026")
            zf.writestr("extra/readme.md", b"# Release Notes\nEnjoy this high quality release.")
            # 4. Unusual filenames (unicode, spaces, punctuation)
            zf.writestr("art/Variant [1-in-25] Cover (Special).jpg", b"\xff\xd8\xff\xe0" + b"variant_cover_data")
            zf.writestr("extra/Crédits & Remerciements.txt", b"Special thanks to the archivist.")
            # 5. Existing ComicInfo.xml
            zf.writestr("ComicInfo.xml", b"<ComicInfo><Series>Old Batman</Series><Number>1</Number></ComicInfo>")
        return cbz_path

    def test_strict_sha256_manifest_computation(self):
        """compute_archive_sha256_manifest maps all non-ComicInfo files correctly."""
        cbz_path = self._create_complex_archive("test_manifest.cbz")
        manifest = compute_archive_sha256_manifest(cbz_path)

        self.assertNotIn("comicinfo.xml", manifest)
        self.assertIn("001.jpg", manifest)
        self.assertIn("002.png", manifest)
        self.assertIn("scans/chapter1/003.webp", manifest)
        self.assertIn("notes.txt", manifest)
        self.assertIn("art/variant [1-in-25] cover (special).jpg", manifest)
        self.assertIn("extra/crédits & remerciements.txt", manifest)

        # Assert correct sha256
        expected_001_sha = hashlib.sha256(b"\xff\xd8\xff\xe0" + b"image_page_1_data_12345").hexdigest()
        self.assertEqual(manifest["001.jpg"], expected_001_sha)

    def test_strict_verification_preserves_all_untouched_sha256(self):
        """Strict verification ensures all non-ComicInfo entries match identical SHA256 after update."""
        cbz_path = self._create_complex_archive("complex_comic.cbz")

        # Record pre-embed SHA256 manifest
        before_manifest = compute_archive_sha256_manifest(cbz_path)
        self.assertEqual(len(before_manifest), 7)

        # Update ComicInfo.xml under strict mode
        new_comic = Comic(
            series="Batman",
            number="1",
            year=2016,
            publisher="DC Comics",
            writers=["Tom King"],
            pencillers=["David Finch"]
        )
        updated_path = embed_comicinfo_in_cbz(cbz_path, new_comic, strict=True)
        self.assertEqual(updated_path, cbz_path)

        # Record post-embed SHA256 manifest
        after_manifest = compute_archive_sha256_manifest(cbz_path)
        self.assertEqual(before_manifest, after_manifest)

    def test_strict_verification_detects_tampered_entry(self):
        """verify_cbz_archive under strict mode raises ArchiveValidationError when SHA256 mismatches."""
        cbz_path = self._create_complex_archive("tampered.cbz")
        manifest = compute_archive_sha256_manifest(cbz_path)

        # Tamper manifest with mismatched hash
        manifest["001.jpg"] = "0000000000000000000000000000000000000000000000000000000000000000"

        with self.assertRaises(ArchiveValidationError) as ctx:
            verify_cbz_archive(cbz_path, strict=True, original_sha256_manifest=manifest)

        self.assertIn("Strict entry SHA256 mismatch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
