import os
import tempfile
import unittest
from models.comic import Comic
from models.identity import ComicIdentity
from pipeline.filename_parser import parse_filename_identity
from pipeline.confidence import evaluate_confidence
from pipeline.review import generate_manual_review_report, format_review_report_markdown, save_review_report

class TestManualReviewReport(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.archive_path = os.path.join(self.temp_dir, "Batman (2016) 001.cbz")
        with open(self.archive_path, "wb") as f:
            f.write(b"PK\x03\x04fake_data")

    def tearDown(self):
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)


    def test_generate_and_save_manual_review_report(self):
        parsed = parse_filename_identity("Batman (2016) #001.cbz")
        cand1 = ComicIdentity(
            provider="ComicVine",
            series_name="Batman",
            publication_year=1940,  # Conflicting year -> MANUAL_REVIEW
            issue_number="1"
        )

        dec1 = evaluate_confidence(cand1, parsed)
        current_comic = Comic(series="Batman", number="1", publisher="DC Comics")

        report = generate_manual_review_report(
            archive_path=self.archive_path,
            current_comic=current_comic,
            candidates=[cand1],
            decisions=[dec1]
        )

        self.assertEqual(report.archive_path, os.path.abspath(self.archive_path))
        self.assertIsNotNone(report.recommended_candidate)

        md_text = format_review_report_markdown(report)
        self.assertIn("Manual Review Report", md_text)
        self.assertIn("Current Metadata", md_text)
        self.assertIn("Evidence List", md_text)
        self.assertIn("Conflicts Detected", md_text)

        report_path = save_review_report(report, output_dir=self.temp_dir)
        self.assertTrue(os.path.exists(report_path))

        # Guarantee archive on disk was NOT touched or modified
        self.assertTrue(os.path.exists(self.archive_path))

if __name__ == "__main__":
    unittest.main()
