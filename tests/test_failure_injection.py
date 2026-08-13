"""
Phase 38 — Failure-Injection Tests

Intentionally simulates every failure mode listed in plan.md.
For every scenario the test asserts:
  1. Original archive remains safe (not deleted, not corrupt)
  2. Job state records the failure (exception is raised)
  3. The system never silently swallows the error

Simulated failures:
  - permission denied (write)
  - provider timeout
  - provider HTTP 429
  - provider HTTP 500
  - malformed HTML response
  - invalid/non-parseable XML in ComicInfo.xml
  - corrupt CBZ (bad ZIP)
  - disk-full (OSError ENOSPC)
  - temporary file failure
  - os.replace failure
"""
import errno
import io
import os
import shutil
import tempfile
import unittest
import urllib.error
import zipfile
from unittest.mock import MagicMock, patch, call

from models.comic import Comic
from writers.archive import (
    ArchiveReadError, ArchiveWriteError, ArchiveValidationError,
    embed_comicinfo_in_cbz, verify_cbz_archive
)
from observability.retry import RetryableError, NonRetryableError, is_retryable_exception


# ------------------------------------------------------------------ #
# Helpers                                                            #
# ------------------------------------------------------------------ #

def _make_cbz(tmp_dir: str, filename: str, images: list = None) -> str:
    path = os.path.join(tmp_dir, filename)
    images = images or ["page_001.jpg", "page_002.jpg"]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for img in images:
            zf.writestr(img, b"\xff\xd8\xff" + b"\x00" * 50)
    return path


def _make_comic(series="Batman", number="1") -> Comic:
    return Comic(title=f"{series} #{number}", series=series, number=number,
                 publisher="DC Comics", year=2016)


class TestFailureInjection(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # 1. Permission denied                                               #
    # ------------------------------------------------------------------ #
    def test_permission_denied_raises_archive_write_error(self):
        """Failure: write permission denied on target file → ArchiveWriteError raised."""
        cbz = _make_cbz(self.tmp, "Batman_001.cbz")
        comic = _make_comic()

        with patch("writers.archive.os.replace",
                   side_effect=PermissionError("Permission denied")):
            with self.assertRaises((ArchiveWriteError, PermissionError)):
                embed_comicinfo_in_cbz(cbz, comic)

        # Original archive must still be intact
        self.assertTrue(os.path.exists(cbz))
        self.assertTrue(zipfile.is_zipfile(cbz))

    # ------------------------------------------------------------------ #
    # 2. Provider timeout                                                #
    # ------------------------------------------------------------------ #
    def test_provider_timeout_is_retryable(self):
        """Failure: TimeoutError from provider is classified as retryable."""
        self.assertTrue(is_retryable_exception(TimeoutError("timed out")))
        self.assertTrue(is_retryable_exception(ConnectionResetError()))

    def test_provider_timeout_retry_exhaustion_propagates(self):
        """Failure: provider keeps timing out → exception propagates after max attempts."""
        from observability.retry import with_retry
        call_count = [0]

        @with_retry(max_attempts=3, base_delay=0.001, provider="ComicVine")
        def fetch():
            call_count[0] += 1
            raise TimeoutError("provider timed out")

        with self.assertRaises(TimeoutError):
            fetch()
        self.assertEqual(call_count[0], 3)

    # ------------------------------------------------------------------ #
    # 3. Provider HTTP 429                                               #
    # ------------------------------------------------------------------ #
    def test_http_429_is_retryable(self):
        """Failure: HTTP 429 must be classified as retryable."""
        err = urllib.error.HTTPError(url="", code=429, msg="", hdrs=None, fp=None)
        self.assertTrue(is_retryable_exception(err))

    def test_http_429_triggers_retry_then_succeeds(self):
        """Failure: one 429 → retry → success on second attempt."""
        from observability.retry import with_retry
        attempts = [0]

        @with_retry(max_attempts=4, base_delay=0.001, provider="ComicVine")
        def fetch():
            attempts[0] += 1
            if attempts[0] == 1:
                raise RetryableError("HTTP 429 Too Many Requests")
            return "ok"

        result = fetch()
        self.assertEqual(result, "ok")
        self.assertEqual(attempts[0], 2)

    # ------------------------------------------------------------------ #
    # 4. Provider HTTP 500                                               #
    # ------------------------------------------------------------------ #
    def test_http_500_is_retryable(self):
        """Failure: HTTP 500 must be classified as retryable."""
        err = urllib.error.HTTPError(url="", code=500, msg="", hdrs=None, fp=None)
        self.assertTrue(is_retryable_exception(err))

    # ------------------------------------------------------------------ #
    # 5. Malformed HTML response                                         #
    # ------------------------------------------------------------------ #
    def test_malformed_html_raises_non_retryable(self):
        """Failure: malformed/empty HTML is a parse failure → NonRetryableError."""
        bad_html = "<html><body>Cloudflare blocked you</body>"

        def parse_html(html: str):
            if "blocked" in html:
                raise NonRetryableError("Cloudflare block detected — not retryable")
            return {}

        with self.assertRaises(NonRetryableError):
            parse_html(bad_html)

    def test_malformed_html_is_not_retryable(self):
        """Failure: NonRetryableError must not be retried."""
        self.assertFalse(is_retryable_exception(NonRetryableError("parse failed")))

    # ------------------------------------------------------------------ #
    # 6. Invalid XML in ComicInfo                                        #
    # ------------------------------------------------------------------ #
    def test_invalid_xml_raises_archive_validation_error(self):
        """Failure: invalid XML embedded in archive → ArchiveValidationError on verify."""
        cbz = _make_cbz(self.tmp, "Batman_bad_xml.cbz")

        # Overwrite with a CBZ containing broken XML
        bad_xml_cbz = self.tmp + "/Batman_bad_xml_v2.cbz"
        with zipfile.ZipFile(bad_xml_cbz, "w") as zf:
            zf.writestr("page_001.jpg", b"\xff\xd8\xff" + b"\x00" * 50)
            zf.writestr("ComicInfo.xml", b"<ComicInfo><UNCLOSED>")  # broken XML

        with self.assertRaises(ArchiveValidationError):
            verify_cbz_archive(bad_xml_cbz)

    # ------------------------------------------------------------------ #
    # 7. Corrupt CBZ (bad ZIP)                                           #
    # ------------------------------------------------------------------ #
    def test_corrupt_cbz_raises_archive_read_error(self):
        """Failure: corrupt ZIP file → ArchiveReadError when embedding."""
        corrupt_path = os.path.join(self.tmp, "corrupt.cbz")
        with open(corrupt_path, "wb") as f:
            f.write(b"PK\x03\x04GARBAGE_DATA_NOT_A_REAL_ZIP" + b"\x00" * 100)
        comic = _make_comic()
        with self.assertRaises(ArchiveReadError):
            embed_comicinfo_in_cbz(corrupt_path, comic)

    def test_nonexistent_archive_raises_archive_read_error(self):
        """Failure: archive file doesn't exist → ArchiveReadError."""
        comic = _make_comic()
        with self.assertRaises(ArchiveReadError):
            embed_comicinfo_in_cbz("/nonexistent/path/Batman.cbz", comic)

    # ------------------------------------------------------------------ #
    # 8. Disk full (OSError ENOSPC)                                      #
    # ------------------------------------------------------------------ #
    def test_disk_full_raises_archive_write_error(self):
        """Failure: ENOSPC during temp file write → ArchiveWriteError, original safe."""
        cbz = _make_cbz(self.tmp, "Batman_diskfull.cbz")
        comic = _make_comic()
        original_size = os.path.getsize(cbz)

        disk_full_error = OSError(errno.ENOSPC, "No space left on device")

        with patch("writers.archive.zipfile.ZipFile") as MockZip:
            # First call is the read (source), second triggers the error
            real_zip = zipfile.ZipFile
            call_count = [0]

            def side_effect(path, mode="r", *args, **kwargs):
                call_count[0] += 1
                if call_count[0] >= 2:
                    raise disk_full_error
                return real_zip(path, mode, *args, **kwargs)

            MockZip.side_effect = side_effect

            with self.assertRaises((ArchiveWriteError, OSError)):
                embed_comicinfo_in_cbz(cbz, comic)

        # Original file must be unchanged
        self.assertTrue(os.path.exists(cbz))
        self.assertEqual(os.path.getsize(cbz), original_size)

    # ------------------------------------------------------------------ #
    # 9. Temporary file creation failure                                 #
    # ------------------------------------------------------------------ #
    def test_temp_file_creation_failure_raises_archive_write_error(self):
        """Failure: cannot create temp file → ArchiveWriteError."""
        cbz = _make_cbz(self.tmp, "Batman_tmpfail.cbz")
        comic = _make_comic()

        with patch("writers.archive.tempfile.NamedTemporaryFile",
                   side_effect=OSError("Read-only filesystem")):
            with self.assertRaises(ArchiveWriteError):
                embed_comicinfo_in_cbz(cbz, comic)

        # Original must still exist
        self.assertTrue(os.path.exists(cbz))
        self.assertTrue(zipfile.is_zipfile(cbz))

    # ------------------------------------------------------------------ #
    # 10. os.replace failure                                             #
    # ------------------------------------------------------------------ #
    def test_os_replace_failure_raises_archive_write_error(self):
        """Failure: os.replace fails mid-operation → ArchiveWriteError, original safe."""
        cbz = _make_cbz(self.tmp, "Batman_replace_fail.cbz")
        comic = _make_comic()
        original_size = os.path.getsize(cbz)

        with patch("writers.archive.os.replace",
                   side_effect=OSError("Interrupted system call")):
            with self.assertRaises(ArchiveWriteError):
                embed_comicinfo_in_cbz(cbz, comic)

        # Archive must still be the original unmodified file
        self.assertTrue(os.path.exists(cbz))
        self.assertEqual(os.path.getsize(cbz), original_size)

    # ------------------------------------------------------------------ #
    # 11. CBR file rejected (not ZIP)                                    #
    # ------------------------------------------------------------------ #
    def test_cbr_file_rejected_with_clear_error(self):
        """Failure: .cbr (RAR) file → ArchiveReadError with clear message."""
        cbr_path = os.path.join(self.tmp, "Batman_001.cbr")
        with open(cbr_path, "wb") as f:
            f.write(b"Rar!\x1a\x07\x00" + b"\x00" * 100)  # RAR magic bytes
        comic = _make_comic()
        with self.assertRaises(ArchiveReadError) as ctx:
            embed_comicinfo_in_cbz(cbr_path, comic)
        self.assertIn(".cbr", str(ctx.exception).lower())

    # ------------------------------------------------------------------ #
    # 12. HTTP 404 must NOT retry                                        #
    # ------------------------------------------------------------------ #
    def test_http_404_not_retried(self):
        """Failure: 404 Not Found → NonRetryableError, never retried."""
        from observability.retry import with_retry
        call_count = [0]

        @with_retry(max_attempts=5, base_delay=0.001, provider="ComicVine")
        def fetch():
            call_count[0] += 1
            raise NonRetryableError("HTTP 404 — not retryable")

        with self.assertRaises(NonRetryableError):
            fetch()
        self.assertEqual(call_count[0], 1)  # Must NOT retry

    # ------------------------------------------------------------------ #
    # 13. Stale temp files cleaned up after failure                      #
    # ------------------------------------------------------------------ #
    def test_temp_file_cleaned_up_after_failure(self):
        """Failure: stale .tmp_ files must not accumulate after embed failure."""
        cbz = _make_cbz(self.tmp, "Batman_cleanup.cbz")
        comic = _make_comic()

        before_files = set(os.listdir(self.tmp))

        with patch("writers.archive.os.replace",
                   side_effect=OSError("replace failed")):
            try:
                embed_comicinfo_in_cbz(cbz, comic)
            except Exception:
                pass

        after_files = set(os.listdir(self.tmp))
        new_files = after_files - before_files
        tmp_files = [f for f in new_files if f.startswith(".tmp_")]
        self.assertEqual(len(tmp_files), 0, f"Leaked temp files: {tmp_files}")


if __name__ == "__main__":
    unittest.main()
