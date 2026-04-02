import unittest

import desktop_app


class DesktopAppTest(unittest.TestCase):
    def test_default_target_date_is_yesterday(self):
        today = desktop_app.now_local().date()
        self.assertEqual(desktop_app.default_target_date(), today - desktop_app.timedelta(days=1))

    def test_build_result_overview_contains_key_sections(self):
        class _Report:
            def summary_lines(self):
                return ["[REPORT] time_window: status=ok"]

        result = {
            "report_date": "2026-03-30",
            "filtered_candidates": [
                {
                    "title": "Test Paper",
                    "primary_category": "cs.CL",
                    "published": None,
                }
            ],
            "cached": {"x": "cache_pdfs/2026-03-30/x.pdf"},
            "json_outputs": {"report": "cache_pdfs/_reports/2026-03-30/pipeline_report.json"},
            "report": _Report(),
        }
        text = desktop_app.build_result_overview(result)
        self.assertIn("\u62a5\u544a\u65e5\u671f: 2026-03-30", text)
        self.assertIn("\u8f93\u51fa\u6587\u4ef6:", text)
        self.assertIn("\u9636\u6bb5\u62a5\u544a:", text)
        self.assertIn("\u8bba\u6587\u5217\u8868:", text)


if __name__ == "__main__":
    unittest.main()
