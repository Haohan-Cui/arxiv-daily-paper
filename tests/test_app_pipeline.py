import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import app
from config import LOCAL_TZ
from pipeline_report import PipelineReport
from runtime_control import PipelineCancelled, PipelineController


class PipelineAppTest(unittest.TestCase):
    def test_parse_institutions_text_supports_alias_rows(self):
        parsed = app.parse_institutions_text("FDU: Fudan University, FDU\nAdobe")
        self.assertEqual(parsed[0]["name"], "FDU")
        self.assertEqual(parsed[0]["terms"], ["Fudan University", "FDU"])
        self.assertEqual(parsed[1], {"name": "Adobe", "terms": ["Adobe"]})

    def test_build_runtime_institution_maps_adds_custom_org(self):
        org_terms, patterns = app.build_runtime_institution_maps([
            {"name": "CustomLab", "terms": ["Custom Lab", "CLab"]}
        ])
        self.assertIn("CustomLab", org_terms)
        self.assertIn('"Custom Lab"', org_terms["CustomLab"])
        self.assertTrue(any("Custom" in pattern for pattern in patterns["CustomLab"]))

    def test_build_candidates_with_fallback_deduplicates(self):
        published = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
        baseline = [{"id": "a", "primary_category": "cs.AI", "published": published, "title": "Alpha", "summary": "", "comment": "", "journal_ref": "", "authors": []}]
        fallback_entry = {"id": "a", "primary_category": "cs.AI", "published": published}
        with mock.patch.object(app, "search_by_terms", return_value=[fallback_entry]), \
             mock.patch.object(app, "is_cs", return_value=True), \
             mock.patch.object(app, "in_time_window", return_value=True):
            merged, stats = app.build_candidates_with_fallback(baseline, object(), object())

        self.assertEqual(len(merged), 1)
        self.assertEqual(stats["merged_candidates"], 1)

    def test_prioritize_candidates_moves_priority_categories_first(self):
        entries = [
            {"id": "http://arxiv.org/abs/2", "primary_category": "cs.SE", "published": datetime(2026, 3, 31, 10, 0, tzinfo=timezone.utc)},
            {"id": "http://arxiv.org/abs/1", "primary_category": "cs.CL", "published": datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc)},
            {"id": "http://arxiv.org/abs/3", "primary_category": "cs.RO", "published": datetime(2026, 3, 31, 8, 0, tzinfo=timezone.utc)},
        ]
        ordered, stats = app.prioritize_candidates(entries)
        self.assertEqual([entry["primary_category"] for entry in ordered[:2]], ["cs.CL", "cs.RO"])
        self.assertEqual(stats["priority_entries"], 2)

    def test_filter_candidates_by_author_affiliation_keeps_only_matches(self):
        entries = [
            {"id": "http://arxiv.org/abs/1", "authors": ["Alice"], "primary_category": "cs.CL"},
            {"id": "http://arxiv.org/abs/2", "authors": ["Bob"], "primary_category": "cs.CL"},
        ]
        with mock.patch.object(app, "classify_from_pdf_with_stats", return_value=({}, {"entry_matches": {"1": ["Tsinghua"]}, "matched_entries": 1, "unmatched_entries": 1, "errors": [], "matched_orgs": {"Tsinghua": 1}})):
            filtered, stats = app.filter_candidates_by_author_affiliation(entries, {"1": "a.pdf", "2": "b.pdf"})
        self.assertEqual(len(filtered), 1)
        self.assertEqual(app.get_arxiv_id(filtered[0]), "1")
        self.assertEqual(stats["kept_entries"], 1)

    def test_write_json_outputs_uses_date_subdirectory(self):
        report = PipelineReport()
        report.stage("time_window").finish()
        start_utc = datetime(2026, 3, 31, 4, 0, 0, tzinfo=timezone.utc)
        entry = {
            "id": "http://arxiv.org/abs/2501.00001v1",
            "authors": ["Alice Zhang"],
            "primary_category": "cs.CL",
            "published": datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
            "title": "LLM Paper",
            "summary": "Summary",
            "comment": "",
            "journal_ref": "",
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")):
            outputs = app.write_json_outputs(start_utc, report, [entry], {"2501.00001v1": "cache.pdf"}, {"2501.00001v1": ["Tsinghua"]})
            self.assertIn("2026-03-31", outputs["report"])
            self.assertTrue(Path(outputs["manifest"]).exists())
            manifest = json.loads(Path(outputs["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["papers"][0]["matched_orgs"], ["Tsinghua"])

    def test_run_pipeline_collects_progress_events(self):
        now = datetime(2026, 4, 1, 13, 0, 0, tzinfo=LOCAL_TZ)
        candidate = {
            "id": "http://arxiv.org/abs/2501.00001v1",
            "authors": ["Alice Zhang"],
            "primary_category": "cs.CL",
            "published": datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
            "title": "LLM Paper",
            "summary": "Summary",
            "comment": "",
            "journal_ref": "",
        }
        events = []
        def callback(stage, message, state, percent):
            events.append((stage, state))

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")), \
             mock.patch.object(app, "_collect_baseline_entries", return_value=([candidate], {"scanned": 1, "matched": 1, "filtered_non_cs": 0, "filtered_out_of_window": 0})), \
             mock.patch.object(app, "build_candidates_with_fallback", return_value=([candidate], {"baseline_candidates": 1, "rough_hit_orgs": 0, "fallback_targets": 0, "merged_candidates": 1, "per_org": {}, "fallback_skipped": True})), \
             mock.patch.object(app, "cache_pdfs_with_stats", return_value=({"2501.00001v1": str(Path(tmpdir) / "2026-03-30" / "paper.pdf")}, {"attempted": 1, "cache_hits": 0, "downloaded": 1, "failed": 0, "errors": [], "cache_dir": str(Path(tmpdir) / "2026-03-30")})), \
             mock.patch.object(app, "filter_candidates_by_author_affiliation", return_value=([candidate], {"entry_matches": {"2501.00001v1": ["Tsinghua"]}, "matched_entries": 1, "unmatched_entries": 0, "kept_entries": 1, "removed_entries": 0, "errors": [], "matched_orgs": {"Tsinghua": 1}})), \
             mock.patch.object(app, "prune_unmatched_cached_pdfs", return_value={"removed_cached_pdfs": 0, "missing_cached_pdfs": 0, "errors": [], "cleanup_enabled": True}):
            result = app.run_pipeline(now=now, target_day=date(2026, 3, 30), progress_callback=callback)

        self.assertEqual(result["report_date"], "2026-03-30")
        self.assertTrue(any(stage == "pdf_cache" for stage, _state in events))
        self.assertIn(("pipeline", "ok"), events)

    def test_run_pipeline_honors_cancellation(self):
        controller = PipelineController()
        controller.cancel()
        with self.assertRaises(PipelineCancelled):
            app.run_pipeline(controller=controller)

    def test_run_pipeline_collects_stage_reports_and_writes_json_for_selected_day(self):
        now = datetime(2026, 4, 1, 13, 0, 0, tzinfo=LOCAL_TZ)
        candidate = {
            "id": "http://arxiv.org/abs/2501.00001v1",
            "authors": ["Alice Zhang"],
            "primary_category": "cs.CL",
            "published": datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
            "title": "LLM Paper",
            "summary": "Summary",
            "comment": "",
            "journal_ref": "",
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")), \
             mock.patch.object(app, "_collect_baseline_entries", return_value=([candidate], {"scanned": 1, "matched": 1, "filtered_non_cs": 0, "filtered_out_of_window": 0})), \
             mock.patch.object(app, "build_candidates_with_fallback", return_value=([candidate], {"baseline_candidates": 1, "rough_hit_orgs": 0, "fallback_targets": 0, "merged_candidates": 1, "per_org": {}, "fallback_skipped": True})), \
             mock.patch.object(app, "cache_pdfs_with_stats", return_value=({"2501.00001v1": str(Path(tmpdir) / "2026-03-30" / "paper.pdf")}, {"attempted": 1, "cache_hits": 0, "downloaded": 1, "failed": 0, "errors": [], "cache_dir": str(Path(tmpdir) / "2026-03-30")})), \
             mock.patch.object(app, "filter_candidates_by_author_affiliation", return_value=([candidate], {"entry_matches": {"2501.00001v1": ["Tsinghua"]}, "matched_entries": 1, "unmatched_entries": 0, "kept_entries": 1, "removed_entries": 0, "errors": [], "matched_orgs": {"Tsinghua": 1}})), \
             mock.patch.object(app, "prune_unmatched_cached_pdfs", return_value={"removed_cached_pdfs": 0, "missing_cached_pdfs": 0, "errors": [], "cleanup_enabled": True}):
            result = app.run_pipeline(now=now, target_day=date(2026, 3, 30))
            report = result["report"]
            self.assertIsInstance(report, PipelineReport)
            self.assertEqual(result["report_date"], "2026-03-30")
            self.assertEqual(report.stage("time_window").metrics["requested_date"], "2026-03-30")
            self.assertEqual(report.stage("author_affiliation_filter").metrics["kept_entries"], 1)
            manifest = json.loads(Path(result["json_outputs"]["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["papers"]), 1)
            self.assertEqual(manifest["papers"][0]["matched_orgs"], ["Tsinghua"])
            self.assertIn("2026-03-30", result["json_outputs"]["manifest"])
            self.assertIn("2026-03-30", report.stage("pdf_cache").metrics["cache_dir"])

    def test_run_pipeline_marks_cache_stage_error_when_all_downloads_fail(self):
        now = datetime(2026, 4, 1, 13, 0, 0, tzinfo=LOCAL_TZ)
        candidate = {
            "id": "http://arxiv.org/abs/2501.00001v1",
            "authors": ["Alice Zhang"],
            "primary_category": "cs.CL",
            "published": datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc),
            "title": "LLM Paper",
            "summary": "Summary",
            "comment": "",
            "journal_ref": "",
        }

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")), \
             mock.patch.object(app, "_collect_baseline_entries", return_value=([candidate], {"scanned": 1, "matched": 1, "filtered_non_cs": 0, "filtered_out_of_window": 0})), \
             mock.patch.object(app, "build_candidates_with_fallback", return_value=([candidate], {"baseline_candidates": 1, "rough_hit_orgs": 0, "fallback_targets": 0, "merged_candidates": 1, "per_org": {}, "fallback_skipped": True})), \
             mock.patch.object(app, "cache_pdfs_with_stats", return_value=({}, {"attempted": 1, "cache_hits": 0, "downloaded": 0, "failed": 1, "errors": ["cache failed"], "cache_dir": str(Path(tmpdir) / "2026-03-31")})), \
             mock.patch.object(app, "filter_candidates_by_author_affiliation", return_value=([], {"entry_matches": {}, "matched_entries": 0, "unmatched_entries": 1, "kept_entries": 0, "removed_entries": 1, "errors": ["missing pdf"], "matched_orgs": {}})), \
             mock.patch.object(app, "prune_unmatched_cached_pdfs", return_value={"removed_cached_pdfs": 0, "missing_cached_pdfs": 1, "errors": [], "cleanup_enabled": True}):
            result = app.run_pipeline(now=now)

        self.assertEqual(result["report"].stage("pdf_cache").status, "error")
        self.assertTrue(result["report"].stage("pdf_cache").errors)


if __name__ == "__main__":
    unittest.main()
