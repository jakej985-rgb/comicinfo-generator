"""
Tests and benchmarks for extract_issue_num_from_filename optimization.
Verifies correct extraction and caching throughput.
"""
import time
import unittest

from services.search import extract_issue_num_from_filename


class TestSearchOptimization(unittest.TestCase):

    def test_accuracy_across_formats(self):
        cases = [
            ("Batman #001 (2016).cbz", "1"),
            ("Superman #02 (2018).cbz", "2"),
            ("Batman #000.cbz", "0"),
            ("Batman issue #0.cbz", "0"),
            ("Batman #0.5.cbz", "0.5"),
            ("Batman #½.cbz", "0.5"),
            ("Batman #1/2.cbz", "0.5"),
            ("Batman #1A.cbz", "1A"),
            ("Batman 001.cbz", "1"),
            ("Flash v2 #100.cbr", "100"),
        ]
        for filename, expected in cases:
            with self.subTest(filename=filename):
                self.assertEqual(extract_issue_num_from_filename(filename), expected)

    def test_lru_cache_active_and_fast(self):
        """Validates that LRU cache is active and provides sub-microsecond lookups."""
        extract_issue_num_from_filename.cache_clear()
        filename = "Batman #001 (2016).cbz"

        # First call populates cache
        res1 = extract_issue_num_from_filename(filename)
        info1 = extract_issue_num_from_filename.cache_info()
        self.assertEqual(info1.misses, 1)
        self.assertEqual(info1.hits, 0)

        # Second call hits cache
        res2 = extract_issue_num_from_filename(filename)
        info2 = extract_issue_num_from_filename.cache_info()
        self.assertEqual(res1, res2)
        self.assertEqual(info2.hits, 1)

        # 50,000 cached calls should execute in under 0.1s
        start = time.perf_counter()
        for _ in range(50000):
            extract_issue_num_from_filename(filename)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.1)


if __name__ == "__main__":
    unittest.main()
