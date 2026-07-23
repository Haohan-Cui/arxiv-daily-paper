import unittest
from datetime import date, datetime, timezone

from config import LOCAL_TZ
from filters import (
    arxiv_day_window,
    arxiv_previous_day_window,
    in_time_window,
    is_cs,
)


class FiltersTest(unittest.TestCase):
    def test_arxiv_day_window_uses_selected_server_day(self):
        start_utc, end_utc = arxiv_day_window(date(2026, 3, 30))
        self.assertEqual(start_utc.isoformat(), "2026-03-30T04:00:00+00:00")
        self.assertEqual(end_utc.isoformat(), "2026-03-31T03:59:59.999999+00:00")

    def test_previous_day_window_uses_arxiv_server_day(self):
        now = datetime(2026, 4, 1, 13, 59, 41, tzinfo=LOCAL_TZ)
        start_utc, end_utc = arxiv_previous_day_window(now)

        self.assertEqual(start_utc.isoformat(), "2026-03-31T04:00:00+00:00")
        self.assertEqual(end_utc.isoformat(), "2026-04-01T03:59:59.999999+00:00")

    def test_in_time_window_only_uses_published(self):
        start_utc = datetime(2026, 3, 31, 4, 0, 0, tzinfo=timezone.utc)
        end_utc = datetime(2026, 4, 1, 3, 59, 59, tzinfo=timezone.utc)
        entry = {
            "published": datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
            "updated": datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc),
        }
        self.assertTrue(in_time_window(entry, start_utc, end_utc))

    def test_is_cs_respects_excluded_categories(self):
        self.assertTrue(is_cs({"primary_category": "cs.AI"}))
        self.assertTrue(is_cs({"primary_category": "math.OC", "categories": ["math.OC", "cs.LG"]}))
        self.assertFalse(is_cs({"primary_category": "cs.GT"}))
        self.assertFalse(is_cs({"primary_category": "cs.NI"}))
        self.assertFalse(is_cs({"primary_category": "cs.PL"}))
        self.assertFalse(is_cs({"primary_category": "cs.DB"}))
        self.assertFalse(is_cs({"primary_category": "math.OC"}))


if __name__ == "__main__":
    unittest.main()
