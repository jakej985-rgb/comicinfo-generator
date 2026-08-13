import os
import unittest
from providers.comicvine.parser import parse_html
from providers.comicvine.client import ComicVineClient
from providers.base import ProviderConnectionError

class TestComicVineOffline(unittest.TestCase):

    def setUp(self):
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures", "comicvine")

    def _read_fixture(self, filename: str) -> str:
        path = os.path.join(self.fixtures_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_parse_batman_2016_001(self):
        html = self._read_fixture("batman_2016_001.html")
        comic = parse_html(html, "https://comicvine.gamespot.com/batman-1/4000-534177/")
        self.assertEqual(comic.series, "Batman")
        self.assertEqual(comic.number, "1")
        self.assertEqual(comic.publisher, "DC Comics")
        self.assertEqual(comic.year, 2016)

    def test_parse_batman_1940_001(self):
        html = self._read_fixture("batman_1940_001.html")
        comic = parse_html(html, "https://comicvine.gamespot.com/batman-1/4000-11111/")
        self.assertEqual(comic.series, "Batman")
        self.assertEqual(comic.number, "1")
        self.assertEqual(comic.publisher, "DC Comics")
        self.assertEqual(comic.year, 1940)
        self.assertIn("Bill Finger", comic.writers)
        self.assertIn("Bob Kane", comic.pencillers)

    def test_parse_marvel_zombies_001(self):
        html = self._read_fixture("marvel_zombies_001.html")
        comic = parse_html(html)
        self.assertEqual(comic.series, "Marvel Zombies")
        self.assertEqual(comic.number, "1")
        self.assertIn("Marvel Zombies", comic.story_arcs)

    def test_parse_dead_days_001(self):
        html = self._read_fixture("dead_days_001.html")
        comic = parse_html(html)
        self.assertEqual(comic.series, "Marvel Zombies: Dead Days")
        self.assertEqual(comic.number, "1")

    def test_parse_annual(self):
        html = self._read_fixture("annual.html")
        comic = parse_html(html)
        self.assertEqual(comic.series, "Batman Annual")
        self.assertEqual(comic.number, "1")

    def test_parse_alternate_cover(self):
        html = self._read_fixture("alternate_cover.html")
        comic = parse_html(html)
        self.assertEqual(comic.series, "Batman")
        self.assertEqual(comic.number, "1B")

    def test_parse_decimal_issue(self):
        html = self._read_fixture("decimal_issue.html")
        comic = parse_html(html)
        self.assertEqual(comic.series, "Spider-Man")
        self.assertEqual(comic.number, "1.5")

    def test_parse_special(self):
        html = self._read_fixture("special.html")
        comic = parse_html(html)
        self.assertEqual(comic.series, "Batman")
        self.assertEqual(comic.number, "0")

    def test_cloudflare_challenge_detection(self):
        html = self._read_fixture("cloudflare.html")
        client = ComicVineClient()
        with self.assertRaises(ProviderConnectionError):
            if "Just a moment..." in html and "<title>Just a moment..." in html:
                raise ProviderConnectionError("Comic Vine returned a Cloudflare verification challenge.", provider_name="CV")

if __name__ == "__main__":
    unittest.main()
