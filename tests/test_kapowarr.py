import unittest
from unittest.mock import patch, MagicMock
from providers.kapowarr import KapowarrProvider

class TestKapowarrProvider(unittest.TestCase):

    def setUp(self):
        self.provider = KapowarrProvider(url="http://localhost:5656", api_key="testkey123")

    @patch("requests.get")
    def test_connection_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        
        self.assertTrue(self.provider.test_connection())

    @patch("requests.get")
    def test_lookup_issue_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 101,
            "title": "The Dark Knight Returns",
            "issue_number": "1",
            "summary": "Batman returns to action.",
            "release_date": "1986-02-01",
            "series": {"name": "Batman: The Dark Knight", "publisher": "DC Comics"},
            "comicvine_id": 4000-9999
        }
        mock_get.return_value = mock_resp

        comic = self.provider.lookup_issue("101")
        self.assertIsNotNone(comic)
        self.assertEqual(comic.series, "Batman: The Dark Knight")
        self.assertEqual(comic.number, "1")
        self.assertEqual(comic.provider_name, "Kapowarr")

if __name__ == "__main__":
    unittest.main()
