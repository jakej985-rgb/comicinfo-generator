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
        mock_resp.json.return_value = {"error": None, "result": []}
        mock_get.return_value = mock_resp
        
        self.assertTrue(self.provider.test_connection())

    @patch("requests.get")
    def test_lookup_issue_success(self, mock_get):
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = {"error": None, "result": [{"id": 1, "name": "Batman"}]}

        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = {
            "error": None,
            "result": {
                "id": 1,
                "name": "Batman: The Dark Knight",
                "publisher": "DC Comics",
                "issues": [
                    {
                        "id": 101,
                        "issue_number": "1",
                        "name": "The Dark Knight Returns",
                        "summary": "Batman returns to action.",
                        "release_date": "1986-02-01",
                        "comicvine_id": 9999
                    }
                ]
            }
        }
        mock_get.side_effect = [mock_resp1, mock_resp2]

        comic = self.provider.lookup_issue("101")
        self.assertIsNotNone(comic)
        self.assertEqual(comic.series, "Batman: The Dark Knight")
        self.assertEqual(comic.number, "1")
        self.assertEqual(comic.provider_name, "Kapowarr")

if __name__ == "__main__":
    unittest.main()
