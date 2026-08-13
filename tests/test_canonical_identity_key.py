"""
Phase 59 — Canonical Comic Identity Key Tests

Verifies:
1. 1 vs 1A (distinct)
2. 1A vs 1B (distinct)
3. 1 vs 1.5 (distinct)
4. 1 vs Annual (distinct)
5. 0 vs 1 (distinct)
6. 10 vs 10.1 (distinct)
7. Volume 1 vs Volume 2 (distinct)
8. 1940 vs 2016 (distinct)
9. Batman #001 (2016) matches Batman #1 (2016)
10. Batman #01A matches Batman #1A
11. Raw issue number strings are strictly preserved without int() casting
"""
import unittest
from models.identity import ComicIdentity, CanonicalIdentityKey
from pipeline.filename_parser import ParsedFilename


class TestCanonicalIdentityKey(unittest.TestCase):

    def test_one_vs_one_a_distinct(self):
        """1 vs 1A are distinct identities."""
        k1 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", publication_year=2016))
        k1a = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1A", publication_year=2016))

        self.assertNotEqual(k1, k1a)
        self.assertFalse(k1.matches(k1a))

    def test_one_a_vs_one_b_distinct(self):
        """1A vs 1B are distinct variant identities."""
        k1a = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1A", publication_year=2016))
        k1b = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1B", publication_year=2016))

        self.assertNotEqual(k1a, k1b)
        self.assertFalse(k1a.matches(k1b))

    def test_one_vs_one_point_five_distinct(self):
        """1 vs 1.5 are distinct fractional identities."""
        k1 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", publication_year=2016))
        k15 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1.5", publication_year=2016))

        self.assertNotEqual(k1, k15)
        self.assertFalse(k1.matches(k15))

    def test_one_vs_annual_distinct(self):
        """1 vs Annual are distinct publication identities."""
        k1 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", publication_year=2016))
        ka = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="Annual", publication_year=2016))

        self.assertNotEqual(k1, ka)
        self.assertFalse(k1.matches(ka))

    def test_zero_vs_one_distinct(self):
        """0 vs 1 are distinct identities."""
        k0 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="0", publication_year=2016))
        k1 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", publication_year=2016))

        self.assertNotEqual(k0, k1)
        self.assertFalse(k0.matches(k1))

    def test_ten_vs_ten_point_one_distinct(self):
        """10 vs 10.1 (decimal point issue numbering) are distinct."""
        k10 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Avengers", issue_number="10", publication_year=2012))
        k101 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Avengers", issue_number="10.1", publication_year=2012))

        self.assertNotEqual(k10, k101)
        self.assertFalse(k10.matches(k101))

    def test_volume_one_vs_volume_two_distinct(self):
        """Volume 1 vs Volume 2 are distinct identities."""
        k_v1 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", volume="1", publication_year=2016))
        k_v2 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", volume="2", publication_year=2016))

        self.assertNotEqual(k_v1, k_v2)
        self.assertFalse(k_v1.matches(k_v2))

    def test_year_1940_vs_2016_distinct(self):
        """1940 vs 2016 are distinct eras."""
        k_1940 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", publication_year=1940))
        k_2016 = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", publication_year=2016))

        self.assertNotEqual(k_1940, k_2016)
        self.assertFalse(k_1940.matches(k_2016))

    def test_padded_issue_number_matches_canonical(self):
        """Batman #001 (2016) matches Batman #1 (2016)."""
        k_pad = CanonicalIdentityKey.from_parsed(ParsedFilename(series_name="Batman", issue_number="001", year=2016))
        k_norm = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1", publication_year=2016))

        self.assertTrue(k_pad.matches(k_norm))
        self.assertEqual(k_pad.issue_numeric, k_norm.issue_numeric)

    def test_padded_variant_matches_canonical(self):
        """Batman #01A matches Batman #1A."""
        k_pad = CanonicalIdentityKey.from_parsed(ParsedFilename(series_name="Batman", issue_number="01A", year=2016))
        k_norm = CanonicalIdentityKey.from_identity(ComicIdentity(series_name="Batman", issue_number="1A", publication_year=2016))

        self.assertTrue(k_pad.matches(k_norm))
        self.assertEqual(k_pad.issue_suffix, "A")

    def test_raw_strings_preserved(self):
        """Raw issue strings are preserved in ComicIdentity without mutation."""
        c = ComicIdentity(series_name="Deadpool", issue_number="½")
        self.assertEqual(c.issue_number, "½")
        self.assertIsInstance(c.canonical_key, CanonicalIdentityKey)


if __name__ == "__main__":
    unittest.main()
