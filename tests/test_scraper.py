import unittest
from scraper.fetcher import Fetcher
from scraper.parser import Parser


class TestFetcher(unittest.TestCase):
    def setUp(self):
        self.fetcher = Fetcher()

    def test_fetch_data(self):
        url = "http://example.com"
        data = self.fetcher.fetch_data(url)
        self.assertIsNotNone(data)
        self.assertIn("<html>", data)  # Basic check to see if HTML is returned


class TestParser(unittest.TestCase):
    def setUp(self):
        self.parser = Parser()

    def test_parse_html(self):
        html = "<html><body><h1>Test</h1></body></html>"
        result = self.parser.parse_html(html)
        self.assertIn(
            "Test", result
        )  # Check if the parsed result contains the expected text


if __name__ == "__main__":
    unittest.main()
