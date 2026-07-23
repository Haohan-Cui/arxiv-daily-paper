import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_build_arg_parser_accepts_headless_mode(self):
        args = desktop_app.build_arg_parser().parse_args([
            "--run-once",
            "--target-day", "2026-04-01",
            "--output-json", "out.json",
        ])
        self.assertTrue(args.run_once)
        self.assertEqual(args.target_day, "2026-04-01")
        self.assertEqual(args.output_json, "out.json")

    def test_save_and_load_institutions_text_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = Path(tmpdir) / "settings.json"
            saved = desktop_app.save_institutions_text(
                "中国人民大学: Renmin University of China, RUC, 中国人民大学\nNYU: New York University, NYU",
                settings_path=settings_path,
            )
            loaded = desktop_app.load_saved_institutions_text(settings_path=settings_path)

        self.assertEqual(saved, loaded)
        self.assertIn("中国人民大学", loaded)
        self.assertIn("New York University", loaded)

    def test_load_saved_institutions_text_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            loaded = desktop_app.load_saved_institutions_text(Path(tmpdir) / "missing.json")
        self.assertIsNone(loaded)

    def test_run_cli_pipeline_writes_json_and_summary(self):
        class _Report:
            def to_dict(self):
                return {"stages": {"time_window": {"status": "ok"}}}

            def summary_lines(self):
                return ["[REPORT] time_window: status=ok"]

        result = {
            "report_date": "2026-04-01",
            "candidates": [{"id": "1"}],
            "ordered_candidates": [{"id": "1"}],
            "filtered_candidates": [{"title": "Paper", "primary_category": "cs.CL", "published": None}],
            "cached": {"1": "cache.pdf"},
            "json_outputs": {"report": "report.json"},
            "report": _Report(),
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(desktop_app, "run_pipeline", return_value=result):
            exit_code = desktop_app.main([
                "--run-once",
                "--target-day", "2026-04-01",
                "--output-json", str(Path(tmpdir) / "result.json"),
                "--output-summary", str(Path(tmpdir) / "summary.txt"),
                "--quiet",
            ])

            self.assertEqual(exit_code, 0)
            payload = json.loads((Path(tmpdir) / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["report_date"], "2026-04-01")
            self.assertEqual(payload["filtered_candidate_count"], 1)
            self.assertTrue((Path(tmpdir) / "summary.txt").exists())

    def test_main_without_run_once_starts_gui(self):
        fake_root = mock.Mock()
        with mock.patch.object(desktop_app, "Tk", return_value=fake_root) as tk_mock, \
             mock.patch.object(desktop_app, "DailyPaperDesktop") as app_mock:
            exit_code = desktop_app.main([])

        self.assertEqual(exit_code, 0)
        tk_mock.assert_called_once()
        app_mock.assert_called_once_with(fake_root)


if __name__ == "__main__":
    unittest.main()
