import unittest
from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.merge import merge_with_policy, MergeResult

def make_issue(number, title="", summary="", publisher="DC Comics",
               year=0, writers=None, characters=None, story_arcs=None,
               web="", provider_id="", provider_name=""):
    return Comic(
        number=number,
        title=title,
        series="Batman",
        summary=summary,
        publisher=publisher,
        year=year,
        writers=writers or [],
        characters=characters or [],
        story_arcs=story_arcs or [],
        web=web,
        provider_id=provider_id,
        provider_name=provider_name,
    )

class TestMergePolicy(unittest.TestCase):

    def test_title_from_collection_override(self):
        """Phase 29: Title priority — collection_override wins."""
        issues = [make_issue("1"), make_issue("2"), make_issue("3")]
        override = Comic(title="Batman: Year One", series="Batman")
        result = merge_with_policy(issues, collection_override=override)
        self.assertEqual(result.comic.title, "Batman: Year One")
        sources = {p.field_name: p.source for p in result.provenance}
        self.assertEqual(sources["title"], "collection_override")

    def test_title_generated_range_fallback(self):
        """Phase 29: Without override, title is generated from issue range."""
        issues = [make_issue("1"), make_issue("2"), make_issue("3")]
        result = merge_with_policy(issues)
        self.assertIn("Batman", result.comic.title)
        self.assertIn("1-3", result.comic.title)

    def test_publisher_kapowarr_wins(self):
        """Phase 29: Publisher — Kapowarr identity beats issue provider."""
        issues = [make_issue("1", publisher="DC"), make_issue("2", publisher="DC")]
        kap = ComicIdentity(provider="Kapowarr", publisher="DC Comics (Verified)")
        result = merge_with_policy(issues, kapowarr_identity=kap)
        self.assertEqual(result.comic.publisher, "DC Comics (Verified)")
        sources = {p.field_name: p.source for p in result.provenance}
        self.assertEqual(sources["publisher"], "Kapowarr")

    def test_year_collection_override_wins(self):
        """Phase 29: Year — collection publication year beats issue year."""
        issues = [make_issue("1", year=2016), make_issue("2", year=2016)]
        override = Comic(year=2017, month=5)
        result = merge_with_policy(issues, collection_override=override)
        self.assertEqual(result.comic.year, 2017)
        self.assertEqual(result.comic.month, 5)
        sources = {p.field_name: p.source for p in result.provenance}
        self.assertEqual(sources["year"], "collection_override")

    def test_year_earliest_issue_fallback(self):
        """Phase 29: Without override, year comes from earliest issue."""
        issues = [make_issue("1", year=2016), make_issue("2", year=2015)]
        result = merge_with_policy(issues)
        self.assertEqual(result.comic.year, 2015)  # earliest

    def test_summary_collection_override(self):
        """Phase 29: Summary — collection override beats per-issue summaries."""
        issues = [
            make_issue("1", summary="Bruce Wayne becomes Batman."),
            make_issue("2", summary="The Joker escapes Arkham."),
        ]
        override = Comic(summary="The definitive Batman origin story.")
        result = merge_with_policy(issues, collection_override=override)
        self.assertEqual(result.comic.summary, "The definitive Batman origin story.")

    def test_summary_per_issue_with_headers(self):
        """Phase 28: Without override, per-issue summaries preserved with issue headers."""
        issues = [
            make_issue("1", summary="Bruce Wayne becomes Batman."),
            make_issue("2", summary="The Joker escapes Arkham."),
        ]
        result = merge_with_policy(issues)
        self.assertIn("Issue #1", result.comic.summary)
        self.assertIn("Issue #2", result.comic.summary)
        self.assertIn("Bruce Wayne becomes Batman.", result.comic.summary)
        self.assertIn("The Joker escapes Arkham.", result.comic.summary)

    def test_characters_union_deduplicated(self):
        """Phase 28 & 29: Characters are union-merged and deduplicated."""
        issues = [
            make_issue("1", characters=["Batman", "Alfred"]),
            make_issue("2", characters=["Batman", "Joker"]),
            make_issue("3", characters=["Joker", "Commissioner Gordon"]),
        ]
        result = merge_with_policy(issues)
        chars = result.comic.characters
        self.assertIn("Batman", chars)
        self.assertIn("Alfred", chars)
        self.assertIn("Joker", chars)
        self.assertIn("Commissioner Gordon", chars)
        # Deduplication: Batman and Joker should each appear exactly once
        self.assertEqual(chars.count("Batman"), 1)
        self.assertEqual(chars.count("Joker"), 1)

    def test_creators_union_deduplicated(self):
        """Phase 28 & 29: Writers are union-merged and deduplicated per role."""
        issues = [
            make_issue("1", writers=["Tom King"]),
            make_issue("2", writers=["Tom King", "Scott Snyder"]),
        ]
        result = merge_with_policy(issues)
        self.assertEqual(result.comic.writers.count("Tom King"), 1)
        self.assertIn("Scott Snyder", result.comic.writers)

    def test_story_arcs_union_deduplicated(self):
        """Phase 28: Story arcs are union-merged and deduplicated."""
        issues = [
            make_issue("1", story_arcs=["Zero Year"]),
            make_issue("2", story_arcs=["Zero Year", "Batman Eternal"]),
        ]
        result = merge_with_policy(issues)
        self.assertEqual(result.comic.story_arcs.count("Zero Year"), 1)
        self.assertIn("Batman Eternal", result.comic.story_arcs)

    def test_provider_id_collection_override(self):
        """Phase 28: Provider ID — collection override beats issue ID."""
        issues = [make_issue("1", provider_id="cv-123", provider_name="ComicVine")]
        override = Comic(provider_id="cv-collection-999", provider_name="ComicVine")
        result = merge_with_policy(issues, collection_override=override)
        self.assertEqual(result.comic.provider_id, "cv-collection-999")

    def test_web_urls_joined_when_no_override(self):
        """Phase 28: Source URLs joined from all issues when no collection override."""
        issues = [
            make_issue("1", web="https://comicvine.gamespot.com/1"),
            make_issue("2", web="https://comicvine.gamespot.com/2"),
        ]
        result = merge_with_policy(issues)
        self.assertIn("https://comicvine.gamespot.com/1", result.comic.web)
        self.assertIn("https://comicvine.gamespot.com/2", result.comic.web)

    def test_format_is_trade_paperback(self):
        issues = [make_issue("1"), make_issue("2")]
        result = merge_with_policy(issues)
        self.assertEqual(result.comic.format, "Trade Paperback")

    def test_count_equals_number_of_issues(self):
        issues = [make_issue("1"), make_issue("2"), make_issue("3")]
        result = merge_with_policy(issues)
        self.assertEqual(result.comic.count, 3)

    def test_empty_issues_returns_empty_comic(self):
        result = merge_with_policy([])
        self.assertIsInstance(result.comic, Comic)


if __name__ == "__main__":
    unittest.main()
