import unittest
from models.identity import ComicIdentity
from pipeline.filename_parser import parse_filename_identity
from pipeline.confidence import evaluate_confidence, LEVEL_AUTO_ACCEPT, LEVEL_MANUAL_REVIEW, LEVEL_UNRESOLVED

class TestConfidenceAndScoring(unittest.TestCase):

    def test_parse_filename_identity(self):
        parsed = parse_filename_identity("/comics/Batman (2016)/Batman #001 - I Am Gotham.cbz")
        self.assertEqual(parsed.series_name, "Batman")
        self.assertEqual(parsed.issue_number, "1")
        self.assertEqual(parsed.year, 2016)

    def test_score_exact_match_auto_accept(self):
        parsed = parse_filename_identity("Batman (2016) #001.cbz")
        candidate = ComicIdentity(
            provider="ComicVine",
            issue_id="4000-12345",
            series_name="Batman",
            publication_year=2016,
            issue_number="1"
        )
        decision = evaluate_confidence(candidate, parsed)
        self.assertGreaterEqual(decision.score, 90.0)
        self.assertEqual(decision.level, LEVEL_AUTO_ACCEPT)
        self.assertEqual(decision.action, "UPDATE")

    def test_score_conflicting_series_unresolved(self):
        parsed = parse_filename_identity("Batman #001.cbz")
        candidate = ComicIdentity(
            provider="ComicVine",
            series_name="Superman",
            issue_number="1"
        )
        decision = evaluate_confidence(candidate, parsed)
        self.assertLess(decision.score, 50.0)
        self.assertEqual(decision.level, LEVEL_UNRESOLVED)
        self.assertEqual(decision.action, "SKIP")

if __name__ == "__main__":
    unittest.main()
