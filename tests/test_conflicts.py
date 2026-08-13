import unittest
from models.identity import ComicIdentity
from pipeline.filename_parser import parse_filename_identity
from pipeline.confidence import evaluate_confidence, LEVEL_MANUAL_REVIEW
from pipeline.conflicts import detect_conflicts, SEVERITY_FATAL

class TestConflictDetection(unittest.TestCase):

    def test_detect_year_conflict_downgrades_to_review(self):
        parsed = parse_filename_identity("Batman (2016) #001.cbz")
        # Candidate has matching series & issue, but conflicting year 1940
        candidate = ComicIdentity(
            provider="ComicVine",
            series_name="Batman",
            publication_year=1940,
            issue_number="1"
        )
        conflicts = detect_conflicts(candidate, parsed)
        self.assertTrue(any(c.type == "year_conflict" and c.severity == SEVERITY_FATAL for c in conflicts))

        decision = evaluate_confidence(candidate, parsed)
        self.assertEqual(decision.level, LEVEL_MANUAL_REVIEW)
        self.assertEqual(decision.action, "REVIEW")

    def test_detect_series_conflict(self):
        parsed = parse_filename_identity("Batman #001.cbz")
        candidate = ComicIdentity(
            provider="ComicVine",
            series_name="Superman",
            issue_number="1"
        )
        conflicts = detect_conflicts(candidate, parsed)
        self.assertTrue(any(c.type == "series_conflict" for c in conflicts))

if __name__ == "__main__":
    unittest.main()
