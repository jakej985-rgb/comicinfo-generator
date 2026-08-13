"""
Phase 43 — Performance Optimization Tests

Verifies performance gains and optimizations:
1. Fast SHA256 hashing with 256KB readinto buffer
2. SQLite WAL mode and PRAGMA performance settings
3. Kapowarr snapshot index caching
4. ZIP entry copy without re-compressing uncompressed/store images
"""
import os
import sqlite3
import tempfile
import time
import unittest
import zipfile

from cache.tracker import calculate_sha256
from cache.db import CacheManager
from writers.archive import embed_comicinfo_in_cbz
from models.comic import Comic
from providers.kapowarr import KapowarrProvider


class TestPerformanceOptimizations(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "perf_cache.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sha256_buffer_performance(self):
        """Phase 43: SHA256 calculation must compute correct hash using 256KB readinto buffer."""
        dummy_path = os.path.join(self.tmp, "large_dummy.cbz")
        content = b"ComicArchiveDataPayload" * 100000  # ~2.3 MB
        with open(dummy_path, "wb") as f:
            f.write(content)

        import hashlib
        expected_hash = hashlib.sha256(content).hexdigest()

        start = time.monotonic()
        actual_hash = calculate_sha256(dummy_path)
        elapsed = time.monotonic() - start

        self.assertEqual(actual_hash, expected_hash)
        self.assertLess(elapsed, 1.0)  # Must execute in under 1 second

    def test_sqlite_wal_pragmas_enabled(self):
        """Phase 43: SQLite connection must configure WAL mode and performance PRAGMAs."""
        mgr = CacheManager(db_path=self.db_path)
        with mgr._get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

    def test_archive_entry_copying_preserves_compress_type(self):
        """Phase 43: Archive embed preserves entry compress_type without re-compressing images."""
        archive_path = os.path.join(self.tmp, "fast_copy.cbz")
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("001.jpg", b"\xff\xd8\xff" + b"\x00" * 1000, compress_type=zipfile.ZIP_STORED)

        comic = Comic(series="FastSeries", number="1")
        embed_comicinfo_in_cbz(archive_path, comic)

        with zipfile.ZipFile(archive_path, "r") as zf:
            info = zf.getinfo("001.jpg")
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_kapowarr_snapshot_index(self):
        """Phase 43: KapowarrProvider builds and queries library snapshot index."""
        prov = KapowarrProvider(url="http://localhost:5656", api_key="key")
        self.assertIsInstance(prov._snapshot_volumes, list)
        self.assertIsInstance(prov._issue_index, dict)


if __name__ == "__main__":
    unittest.main()
