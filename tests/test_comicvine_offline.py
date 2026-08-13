import os
import unittest
from providers.comicvine import parse_html

class TestComicVineOffline(unittest.TestCase):

    def setUp(self):
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures", "comicvine")

    def test_parse_batman_issue_html(self):
        fixture_path = os.path.join(self.fixtures_dir, "batman_issue.html")
        with open(fixture_path, "r", encoding="utf-8") as f:
            html = f.read()

        comic = parse_html(html, "https://comicvine.gamespot.com/batman-1/4000-534177/")
        self.assertEqual(comic.series, "Batman")
        self.assertEqual(comic.number, "1")
        self.assertEqual(comic.publisher, "DC Comics")
        self.assertIn("Tom King", comic.writers)
        self.assertIn("David Finch", comic.pencillers)
        self.assertEqual(comic.year, 2016)

if __name__ == "__main__":
    unittest.main()
