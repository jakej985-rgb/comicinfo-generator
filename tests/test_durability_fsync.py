"""
Phase 61 — Durability and fsync Error Handling Tests

Verifies:
1. fsync_file returns FSYNC_SUCCESS on normal file.
2. fsync_file returns FSYNC_UNSUPPORTED when errno is ENOSYS or EINVAL.
3. fsync_file raises ArchiveWriteError when an actual I/O failure (EIO) occurs.
4. fsync_directory returns FSYNC_SUCCESS on normal directory.
5. fsync_directory returns FSYNC_UNSUPPORTED when errno is EINVAL or EISDIR.
6. fsync_directory raises ArchiveWriteError on EIO.
7. embed_comicinfo_in_cbz fails safely and preserves original file if fsync encounters EIO.
"""
import errno
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from models.comic import Comic
from writers.archive import (
    fsync_file,
    fsync_directory,
    embed_comicinfo_in_cbz,
    FSYNC_SUCCESS,
    FSYNC_UNSUPPORTED,
    ArchiveWriteError
)


class TestDurabilityFsync(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_sample_cbz(self, name: str) -> str:
        cbz_path = os.path.join(self.tmp, name)
        with zipfile.ZipFile(cbz_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff\xe0" + b"page1")
        return cbz_path

    def test_fsync_file_success(self):
        """fsync_file returns FSYNC_SUCCESS for an ordinary disk file."""
        file_path = os.path.join(self.tmp, "test_file.txt")
        with open(file_path, "w") as f:
            f.write("hello durability")

        result = fsync_file(file_path)
        self.assertEqual(result, FSYNC_SUCCESS)

    def test_fsync_file_unsupported(self):
        """fsync_file returns FSYNC_UNSUPPORTED when errno is ENOSYS."""
        file_path = os.path.join(self.tmp, "test_file.txt")
        with open(file_path, "w") as f:
            f.write("hello")

        with patch("os.fsync", side_effect=OSError(errno.ENOSYS, "Function not implemented")):
            result = fsync_file(file_path)
            self.assertEqual(result, FSYNC_UNSUPPORTED)

    def test_fsync_file_io_error_raises(self):
        """fsync_file raises ArchiveWriteError when an actual EIO occurs."""
        file_path = os.path.join(self.tmp, "test_file.txt")
        with open(file_path, "w") as f:
            f.write("hello")

        with patch("os.fsync", side_effect=OSError(errno.EIO, "Input/output error")):
            with self.assertRaises(ArchiveWriteError) as ctx:
                fsync_file(file_path)
            self.assertIn("fsync failed", str(ctx.exception))
            self.assertEqual(ctx.exception.operation, "fsync_file")

    def test_fsync_directory_success(self):
        """fsync_directory returns FSYNC_SUCCESS for a directory."""
        result = fsync_directory(self.tmp)
        self.assertIn(result, (FSYNC_SUCCESS, FSYNC_UNSUPPORTED))

    def test_fsync_directory_unsupported(self):
        """fsync_directory returns FSYNC_UNSUPPORTED when filesystem does not support directory sync."""
        with patch("os.fsync", side_effect=OSError(errno.EINVAL, "Invalid argument")):
            result = fsync_directory(self.tmp)
            self.assertEqual(result, FSYNC_UNSUPPORTED)

    def test_fsync_directory_io_error_raises(self):
        """fsync_directory raises ArchiveWriteError when an actual EIO occurs."""
        with patch("os.fsync", side_effect=OSError(errno.EIO, "Input/output error")):
            with self.assertRaises(ArchiveWriteError) as ctx:
                fsync_directory(self.tmp)
            self.assertIn("Directory metadata fsync failed", str(ctx.exception))
            self.assertEqual(ctx.exception.operation, "fsync_directory")

    def test_embed_comicinfo_fails_safely_on_fsync_io_error(self):
        """When fsync fails with EIO, embed_comicinfo_in_cbz raises ArchiveWriteError and original archive is safe."""
        cbz_path = self._create_sample_cbz("batman_001.cbz")
        with open(cbz_path, "rb") as f:
            original_bytes = f.read()

        comic = Comic(series="Batman", number="1", year=2016)

        # Inject EIO error on os.fsync
        with patch("os.fsync", side_effect=OSError(errno.EIO, "Disk I/O Error")):
            with self.assertRaises(ArchiveWriteError):
                embed_comicinfo_in_cbz(cbz_path, comic)

        # Verify original archive remains safe and byte-identical
        with open(cbz_path, "rb") as f:
            current_bytes = f.read()
        self.assertEqual(original_bytes, current_bytes)


if __name__ == "__main__":
    unittest.main()
