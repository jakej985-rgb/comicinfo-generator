import os
import tempfile
import unittest
import zipfile
from models.comic import Comic
from writers.comicinfo import ComicInfoWriter
from pipeline.issue_number import IssueNumber
from pipeline.identity import extract_identity_candidates

class TestIdentityExtraction(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_issue_number_parsing(self):
        i1 = IssueNumber.parse("1")
        i001 = IssueNumber.parse("001")
        self.assertTrue(i1.matches(i001))
        self.assertEqual(i1.clean, "1")

        i1a = IssueNumber.parse("1A")
        self.assertEqual(i1a.clean, "1A")
        self.assertFalse(i1.matches(i1a))

        i_half = IssueNumber.parse("1/2")
        self.assertEqual(i_half.clean, "0.5")

        i_ann = IssueNumber.parse("Annual 2021")
        self.assertTrue(i_ann.is_annual)

    def test_extract_identity_candidates(self):
        folder = os.path.join(self.temp_dir.name, "Batman (2016)")
        os.makedirs(folder, exist_ok=True)
        cbz_path = os.path.join(folder, "Batman #001.cbz")

        comic = Comic(title="I Am Gotham", series="Batman", number="1", year=2016, publisher="DC Comics")
        xml_data = ComicInfoWriter.generate_xml_bytes(comic)

        with zipfile.ZipFile(cbz_path, "w") as z:
            z.writestr("page1.jpg", b"dummy")
            z.writestr("ComicInfo.xml", xml_data)

        candidates = extract_identity_candidates(cbz_path)
        self.assertGreaterEqual(len(candidates), 1)

        filename_cand = [c for c in candidates if c.provider == "FilenameParser"][0]
        self.assertEqual(filename_cand.series_name, "Batman")
        self.assertEqual(filename_cand.issue_number, "1")
        self.assertEqual(filename_cand.publication_year, 2016)

if __name__ == "__main__":
    unittest.main()
