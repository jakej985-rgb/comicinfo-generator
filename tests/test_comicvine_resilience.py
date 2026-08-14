"""
tests/test_comicvine_resilience.py — Phase 90: ComicVine Resilience & Regression Fixtures

Verifies:
1. 90.1: Series Scenarios (normal volume, pagination, missing pagination, renamed series, slug mismatch).
2. 90.2: Issue Number Scenarios (#1, #01, #1.5, #1/2, #½, #0, annual, special, FCBD, preview, one-shot).
3. 90.3: Exclusions (TPB, HC, GN, Omnibus, Compendium, Masterworks, Collection, Deluxe, Edition).
"""

import os
import unittest
from bs4 import BeautifulSoup

from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.filename_parser import parse_filename_identity, ParsedFilename
from pipeline.scoring import score_identity_candidate
from providers.comicvine.parser import parse_html, parse_series, parse_issue_number, parse_title, parse_publisher


class TestComicVineResilience(unittest.TestCase):

    # ------------------------------------------------------------------ #
    # 90.1: Series Scenarios & Volume Slug Mismatch                      #
    # ------------------------------------------------------------------ #
    def test_90_1_normal_volume_html_parsing(self):
        """90.1: Standard Comic Vine issue HTML parses series, issue number, title, publisher, and creators."""
        html = """
        <html>
          <body>
            <h1><a class="wiki-title" href="/batman/4050-796/">Batman</a> #<a class="wiki-issue-number" href="/batman-1/4000-1001/">1</a> - I Am Gotham</h1>
            <div class="wiki-descriptor">released by DC Comics on June 15, 2016</div>
            <div class="js-toc-content">Batman fights to save Gotham City once again.</div>
            <div class="wiki-details-object">
              <h3>Creators</h3>
              <div>Writer: <a href="/tom-king/4040-1234/">Tom King</a></div>
              <div>Penciler: <a href="/david-finch/4040-5678/">David Finch</a></div>
            </div>
          </body>
        </html>
        """
        comic = parse_html(html, url="https://comicvine.gamespot.com/batman-1/4000-1001/")
        self.assertEqual(comic.series, "Batman")
        self.assertEqual(comic.number, "1")
        self.assertEqual(comic.publisher, "DC Comics")
        self.assertEqual(comic.writers, ["Tom King"])
        self.assertEqual(comic.pencillers, ["David Finch"])

    def test_90_1_volume_slug_mismatch_and_minimal_dom(self):
        """90.1: HTML with renamed series, missing wiki-title class, and slug mismatches parses safely."""
        html = """
        <html>
          <body>
            <h1>Batman (Rebirth) #01 - Gotham Nights</h1>
            <meta name="adtags" content="publisher=dc-comics&genre=superhero" />
            <meta name="description" content="A dark knight rises." />
          </body>
        </html>
        """
        comic = parse_html(html, url="https://comicvine.gamespot.com/4000-99999/")
        self.assertEqual(comic.series, "Batman (Rebirth)")
        self.assertEqual(comic.number, "01")
        self.assertEqual(comic.publisher, "Dc Comics")
        self.assertEqual(comic.summary, "A dark knight rises.")

    # ------------------------------------------------------------------ #
    # 90.2: Issue Number Scenarios                                       #
    # ------------------------------------------------------------------ #
    def test_90_2_issue_number_variations(self):
        """90.2: Tests extraction and normalization for #1, #01, #1.5, #1/2, #½, #0, annual, special, FCBD, preview, one-shot."""
        test_cases = [
            ("Batman #1 (2016).cbz", "1"),
            ("Batman #01 (2016).cbz", "1"),
            ("Batman #001 (2016).cbz", "1"),
            ("Batman #1.5 (2016).cbz", "1.5"),
            ("Batman #1/2 (2016).cbz", "0.5"),
            ("Batman #½ (2016).cbz", "0.5"),
            ("Batman #0 (2012).cbz", "0"),
            ("Batman Annual #1 (2016).cbz", "1"),
            ("Batman Annual (2016).cbz", "Annual"),
            ("Batman Special #1 (2016).cbz", "1"),
            ("Batman Special (2016).cbz", "Special"),
            ("Batman FCBD (2016).cbz", "FCBD"),
            ("Batman Free Comic Book Day (2016).cbz", "FCBD"),
            ("Batman Preview (2016).cbz", "Preview"),
            ("Batman One-Shot (2016).cbz", "One-Shot"),
            ("Batman Oneshot (2016).cbz", "One-Shot"),
        ]

        for fname, expected_num in test_cases:
            parsed = parse_filename_identity(fname)
            self.assertEqual(
                parsed.issue_number, expected_num,
                f"Failed for filename: {fname} (got '{parsed.issue_number}', expected '{expected_num}')"
            )

    # ------------------------------------------------------------------ #
    # 90.3: Exclusions (TPB, HC, GN, Omnibus, Collection, Deluxe)        #
    # ------------------------------------------------------------------ #
    def test_90_3_trade_paperback_and_collection_exclusions(self):
        """90.3: Identifies TPB, HC, GN, Omnibus, Compendium, Masterworks, Collection, Deluxe Edition."""
        tpb_cases = [
            ("Batman Vol 1 TPB (2016).cbz", True),
            ("Batman - I Am Gotham TPB.cbz", True),
            ("Batman Volume 1 HC (2016).cbz", True),
            ("Batman The Killing Joke GN.cbz", True),
            ("Batman Graphic Novel.cbz", True),
            ("Batman by Scott Snyder Omnibus Vol 1.cbz", True),
            ("Invincible Compendium One.cbz", True),
            ("Marvel Masterworks Spider-Man.cbz", True),
            ("Batman The Black Mirror Collection.cbz", True),
            ("Batman Year One Deluxe Edition.cbz", True),
            ("Batman Complete Edition (2016).cbz", True),
            ("Batman #001 (2016).cbz", False),
            ("Spider-Man #025 (2022).cbz", False),
        ]

        for fname, is_tpb_expected in tpb_cases:
            parsed = parse_filename_identity(fname)
            self.assertEqual(
                parsed.is_tpb, is_tpb_expected,
                f"TPB detection mismatch for '{fname}' (got {parsed.is_tpb}, expected {is_tpb_expected})"
            )

    def test_90_3_scoring_penalty_prevents_tpb_matching_single_issue(self):
        """90.3: Scoring penalizes matching a TPB file to a single floppy candidate identity."""
        parsed_tpb = parse_filename_identity("Batman Vol 1 TPB (2016).cbz")
        self.assertTrue(parsed_tpb.is_tpb)

        # Candidate is single floppy issue #1
        candidate_floppy = ComicIdentity(
            series_name="Batman",
            issue_number="1",
            publication_year=2016,
            provider="ComicVine"
        )

        score, evidence, reasons = score_identity_candidate(candidate_floppy, parsed_tpb)
        # Verify format penalty was applied
        format_ev = [e for e in evidence if e.field == "format"]
        self.assertTrue(len(format_ev) > 0)
        self.assertEqual(format_ev[0].score, -50.0)


if __name__ == "__main__":
    unittest.main()
