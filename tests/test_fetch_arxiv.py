import unittest
from datetime import datetime, timezone
from unittest import mock

import fetch_arxiv


class _Feed:
    def __init__(self, entries):
        self.entries = entries


class FetchArxivTest(unittest.TestCase):
    def test_validate_api_payload_rejects_html(self):
        with self.assertRaises(ValueError):
            fetch_arxiv._validate_api_payload("<html>vpn login</html>")

    def test_search_by_terms_stops_when_page_is_older_than_window(self):
        old = {
            "id": "http://arxiv.org/abs/1",
            "published": datetime(2026, 3, 30, 0, 0, tzinfo=timezone.utc),
            "updated": None,
            "title": "old",
            "summary": "",
            "authors": [],
            "primary_category": "cs.AI",
            "comment": "",
            "journal_ref": "",
            "links": [],
        }
        with mock.patch.object(fetch_arxiv, "_query_any", return_value=_Feed([old])), \
             mock.patch.object(fetch_arxiv, "_entry_to_dict", side_effect=lambda entry: entry):
            rows = list(fetch_arxiv.search_by_terms(['"Test"'], limit_pages=3, page_size=10, start_utc=datetime(2026, 3, 31, 4, 0, tzinfo=timezone.utc)))
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
