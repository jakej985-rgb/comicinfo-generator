import unittest
from models.identity import ComicIdentity
from pipeline.issue_order import parse_issue_order, sort_issues, IssueOrder
from pipeline.collection import (
    CollectionIssue, validate_collection,
    RESULT_ACCEPT, RESULT_WARN, RESULT_REJECT
)

def make_identity(series="Batman", publisher="DC Comics", volume_id="4000-123"):
    return ComicIdentity(
        provider="ComicVine",
        series_name=series,
        publisher=publisher,
        volume_id=volume_id
    )

class TestIssueOrder(unittest.TestCase):

    def test_numeric_ordering(self):
        numbers = ["3", "1", "2", "0", "0.5", "1.5"]
        result = sort_issues(numbers)
        self.assertEqual(result, ["0", "0.5", "1", "1.5", "2", "3"])

    def test_letter_suffix_ordering(self):
        numbers = ["1B", "1A", "1"]
        result = sort_issues(numbers)
        # "1" has no suffix, sorts before "1A" and "1B"
        self.assertEqual(result[0], "1")
        self.assertEqual(result[1], "1A")
        self.assertEqual(result[2], "1B")

    def test_named_types_sort_after_numbers(self):
        numbers = ["Annual", "1", "2", "Special"]
        result = sort_issues(numbers)
        self.assertEqual(result[:2], ["1", "2"])
        self.assertIn("Annual", result[2:])
        self.assertIn("Special", result[2:])

    def test_zero_issue(self):
        order = parse_issue_order("0")
        self.assertEqual(order.numeric_value, 0.0)
        self.assertEqual(order.letter_suffix, "")

    def test_fractional_issue(self):
        order = parse_issue_order("0.5")
        self.assertEqual(order.numeric_value, 0.5)

    def test_annual_is_named(self):
        order = parse_issue_order("Annual")
        self.assertTrue(order.is_named)
        self.assertEqual(order.numeric_value, 10000.0)

    def test_annual_case_insensitive(self):
        order = parse_issue_order("ANNUAL")
        self.assertTrue(order.is_named)


class TestCollectionValidation(unittest.TestCase):

    def test_accept_sequential_issues(self):
        """Batman #1, #2, #3 from same series/volume → ACCEPT"""
        issues = [
            CollectionIssue(identity=make_identity(), issue_number="1"),
            CollectionIssue(identity=make_identity(), issue_number="2"),
            CollectionIssue(identity=make_identity(), issue_number="3"),
        ]
        result = validate_collection(issues)
        self.assertEqual(result.result, RESULT_ACCEPT)
        self.assertEqual(result.sorted_issue_numbers, ["1", "2", "3"])

    def test_reject_different_series(self):
        """Batman #1 + Detective Comics #1 → REJECT"""
        issues = [
            CollectionIssue(identity=make_identity(series="Batman"), issue_number="1"),
            CollectionIssue(identity=make_identity(series="Detective Comics"), issue_number="1"),
        ]
        result = validate_collection(issues)
        self.assertEqual(result.result, RESULT_REJECT)
        self.assertTrue(any("series" in msg.lower() for msg in result.issues))

    def test_warn_lettered_variants(self):
        """Batman #1 + Batman #1A → WARN (same base, different variant)"""
        issues = [
            CollectionIssue(identity=make_identity(), issue_number="1"),
            CollectionIssue(identity=make_identity(), issue_number="1A"),
        ]
        result = validate_collection(issues)
        self.assertEqual(result.result, RESULT_WARN)

    def test_reject_different_volumes(self):
        """Same series name but different provider volume IDs → REJECT"""
        issues = [
            CollectionIssue(identity=make_identity(volume_id="4000-111"), issue_number="1"),
            CollectionIssue(identity=make_identity(volume_id="4000-999"), issue_number="2"),
        ]
        result = validate_collection(issues)
        self.assertEqual(result.result, RESULT_REJECT)
        self.assertTrue(any("volume" in msg.lower() for msg in result.issues))

    def test_sorted_output_uses_issue_order(self):
        """Sorted output should never use int() — must handle 1.5, 0, 0.5"""
        issues = [
            CollectionIssue(identity=make_identity(), issue_number="2"),
            CollectionIssue(identity=make_identity(), issue_number="0.5"),
            CollectionIssue(identity=make_identity(), issue_number="1.5"),
            CollectionIssue(identity=make_identity(), issue_number="0"),
            CollectionIssue(identity=make_identity(), issue_number="1"),
        ]
        result = validate_collection(issues)
        self.assertEqual(result.result, RESULT_ACCEPT)
        self.assertEqual(result.sorted_issue_numbers, ["0", "0.5", "1", "1.5", "2"])


if __name__ == "__main__":
    unittest.main()
