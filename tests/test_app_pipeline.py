import json
import sys
import tempfile
import types
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

if "feedparser" not in sys.modules:
    sys.modules["feedparser"] = types.SimpleNamespace(parse=lambda *_args, **_kwargs: None)

import app
from config import LOCAL_TZ
from pipeline_report import PipelineReport
from runtime_control import PipelineCancelled, PipelineController


def _entry(arxiv_id="2606.01779", published=None, category="cs.CL", title="Paper"):
    return {
        "id": f"http://arxiv.org/abs/{arxiv_id}",
        "authors": ["Alice Zhang"],
        "primary_category": category,
        "categories": [category],
        "published": published or datetime(2026, 6, 1, 12, tzinfo=timezone.utc),
        "updated": None,
        "title": title,
        "summary": "",
        "comment": "",
        "journal_ref": "",
        "links": [],
    }


class PipelineAppTest(unittest.TestCase):
    def test_parse_institutions_text_supports_alias_rows(self):
        parsed = app.parse_institutions_text("FDU: Fudan University, FDU\nAdobe")
        self.assertEqual(parsed[0], {"name": "FDU", "terms": ["Fudan University", "FDU"]})
        self.assertEqual(parsed[1], {"name": "Adobe", "terms": ["Adobe"]})

    def test_build_runtime_institution_maps_adds_custom_org(self):
        terms, patterns = app.build_runtime_institution_maps([
            {"name": "CustomLab", "terms": ["Custom Lab", "CLab"]}
        ])
        self.assertIn('"Custom Lab"', terms["CustomLab"])
        self.assertTrue(any("Custom" in pattern for pattern in patterns["CustomLab"]))

    def test_select_candidates_uses_complete_baseline(self):
        baseline = [
            _entry(title="OpenAI study"),
            _entry(arxiv_id="2606.01780", title="Generic study"),
        ]
        candidates, stats = app.select_candidates(
            baseline,
        )
        self.assertEqual(candidates, baseline)
        self.assertEqual(stats["selected_candidates"], 2)
        self.assertEqual(stats["selection_mode"], "complete_calendar_day_cs_baseline")

    def test_collect_baseline_keeps_only_cs_rows_in_selected_day(self):
        start = datetime(2026, 6, 1, 4, tzinfo=timezone.utc)
        end = datetime(2026, 6, 2, 4, tzinfo=timezone.utc)
        rows = [
            _entry(published=datetime(2026, 6, 1, 3, 59, tzinfo=timezone.utc)),
            _entry(arxiv_id="2606.01780", category="math.OC"),
            _entry(arxiv_id="2606.01781"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")), \
             mock.patch.object(app, "iter_recent_cs", return_value=iter(rows)):
            entries, stats = app._collect_baseline_entries(start, end, "2026-06-01")
        self.assertEqual([app.get_arxiv_id(row) for row in entries], ["2606.01781"])
        self.assertEqual(stats["filtered_non_cs"], 1)
        self.assertEqual(stats["filtered_out_of_window"], 1)

    def test_collect_baseline_resumes_from_api_offset(self):
        start = datetime(2026, 6, 1, 4, tzinfo=timezone.utc)
        end = datetime(2026, 6, 2, 4, tzinfo=timezone.utc)
        existing = app._serialize_checkpoint_entry(_entry())
        captured = {}
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")):
            app._write_baseline_checkpoint(
                "2026-06-01",
                start,
                end,
                [app._deserialize_checkpoint_entry(existing)],
                {"scanned": 200, "matched": 1, "filtered_non_cs": 0, "filtered_out_of_window": 0},
                200,
            )

            def iterator(**kwargs):
                captured.update(kwargs)
                yield _entry(arxiv_id="2606.01780")

            with mock.patch.object(app, "iter_recent_cs", side_effect=iterator):
                entries, stats = app._collect_baseline_entries(start, end, "2026-06-01")

        self.assertEqual(captured["start_offset"], 200)
        self.assertEqual(len(entries), 2)
        self.assertEqual(stats["scanned"], 201)

    def test_checkpoint_rejects_old_schema(self):
        start = datetime(2026, 6, 1, 4, tzinfo=timezone.utc)
        end = datetime(2026, 6, 2, 4, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")):
            path = app._baseline_checkpoint_path("2026-06-01")
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "filter_version": "oai_legacy",
            }), encoding="utf-8")
            self.assertIsNone(app._load_baseline_checkpoint("2026-06-01", start, end))

    def test_collect_baseline_uses_complete_cache_without_api(self):
        start = datetime(2026, 6, 1, 4, tzinfo=timezone.utc)
        end = datetime(2026, 6, 2, 4, tzinfo=timezone.utc)
        cached = [_entry()]
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")):
            app._write_complete_baseline_cache("2026-06-01", start, end, cached)
            with mock.patch.object(app, "iter_recent_cs") as iter_mock:
                entries, stats = app._collect_baseline_entries(start, end, "2026-06-01")

        iter_mock.assert_not_called()
        self.assertEqual([app.get_arxiv_id(entry) for entry in entries], ["2606.01779"])
        self.assertTrue(stats["cache_hit"])

    def test_collect_baseline_deduplicates_resumed_entries(self):
        start = datetime(2026, 6, 1, 4, tzinfo=timezone.utc)
        end = datetime(2026, 6, 2, 4, tzinfo=timezone.utc)
        existing = _entry()
        duplicate = _entry()
        fresh = _entry(arxiv_id="2606.01780")
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")):
            app._write_baseline_checkpoint(
                "2026-06-01",
                start,
                end,
                [existing],
                {"scanned": 1, "matched": 1, "filtered_non_cs": 0, "filtered_out_of_window": 0},
                1,
            )
            with mock.patch.object(app, "iter_recent_cs", return_value=iter([duplicate, fresh])):
                entries, stats = app._collect_baseline_entries(start, end, "2026-06-01")

        self.assertEqual([app.get_arxiv_id(entry) for entry in entries], ["2606.01779", "2606.01780"])
        self.assertEqual(stats["matched"], 2)

    def test_prioritize_candidates_moves_priority_categories_first(self):
        entries = [
            _entry(arxiv_id="2", category="cs.SE"),
            _entry(arxiv_id="1", category="cs.CL"),
            _entry(arxiv_id="3", category="cs.RO"),
        ]
        ordered, stats = app.prioritize_candidates(entries)
        self.assertEqual([row["primary_category"] for row in ordered[:2]], ["cs.CL", "cs.RO"])
        self.assertEqual(stats["priority_entries"], 2)

    def test_filter_candidates_keeps_only_pdf_affiliation_matches(self):
        entries = [_entry(arxiv_id="1"), _entry(arxiv_id="2")]
        classify_stats = {
            "entry_matches": {"1": ["Tsinghua"]},
            "matched_entries": 1,
            "unmatched_entries": 1,
            "errors": [],
            "matched_orgs": {"Tsinghua": 1},
        }
        with mock.patch.object(app, "classify_from_pdf_with_stats", return_value=({}, classify_stats)):
            filtered, stats = app.filter_candidates_by_author_affiliation(entries, {"1": "a.pdf", "2": "b.pdf"})
        self.assertEqual([app.get_arxiv_id(row) for row in filtered], ["1"])
        self.assertEqual(stats["kept_entries"], 1)

    def test_write_json_outputs_serializes_datetimes(self):
        report = PipelineReport()
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")):
            outputs = app.write_json_outputs(
                "2026-06-01",
                report,
                [_entry()],
                {"2606.01779": "cache.pdf"},
                {"2606.01779": ["Tsinghua"]},
            )
            payload = json.loads(Path(outputs["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(payload["papers"][0]["matched_orgs"], ["Tsinghua"])
        self.assertIsInstance(payload["papers"][0]["published"], str)

    def test_run_pipeline_honors_cancellation(self):
        controller = PipelineController()
        controller.cancel()
        with self.assertRaises(PipelineCancelled):
            app.run_pipeline(controller=controller)

    def test_run_pipeline_uses_selected_date(self):
        candidate = _entry()
        now = datetime(2026, 6, 3, 12, tzinfo=LOCAL_TZ)
        cache_stats = {
            "attempted": 1,
            "cache_hits": 1,
            "downloaded": 0,
            "failed": 0,
            "errors": [],
            "cache_dir": "tmp",
        }
        author_stats = {
            "entry_matches": {"2606.01779": ["Tsinghua"]},
            "matched_entries": 1,
            "unmatched_entries": 0,
            "kept_entries": 1,
            "removed_entries": 0,
            "errors": [],
            "matched_orgs": {"Tsinghua": 1},
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")), \
             mock.patch.object(app, "_collect_baseline_entries", return_value=([candidate], {
                 "scanned": 1,
                 "matched": 1,
                 "filtered_non_cs": 0,
                 "filtered_out_of_window": 0,
             })), \
             mock.patch.object(app, "cache_pdfs_with_stats", return_value=({"2606.01779": "x.pdf"}, cache_stats)), \
             mock.patch.object(app, "filter_candidates_by_author_affiliation", return_value=([candidate], author_stats)), \
             mock.patch.object(app, "prune_unmatched_cached_pdfs", return_value={
                 "removed_cached_pdfs": 0,
                 "missing_cached_pdfs": 0,
                 "errors": [],
             }):
            result = app.run_pipeline(now=now, target_day=date(2026, 6, 1))
        self.assertEqual(result["report_date"], "2026-06-01")
        self.assertEqual(len(result["filtered_candidates"]), 1)

    def test_run_pipeline_excludes_candidates_without_cached_pdf(self):
        kept = _entry(arxiv_id="2606.01779")
        small = _entry(arxiv_id="2606.01780")
        now = datetime(2026, 6, 3, 12, tzinfo=LOCAL_TZ)
        cache_stats = {
            "attempted": 2,
            "cache_hits": 0,
            "downloaded": 1,
            "skipped_small": 1,
            "failed": 0,
            "errors": [],
            "cache_dir": "tmp",
        }
        author_stats = {
            "entry_matches": {"2606.01779": ["Tsinghua"]},
            "matched_entries": 1,
            "unmatched_entries": 0,
            "kept_entries": 1,
            "removed_entries": 0,
            "errors": [],
            "matched_orgs": {"Tsinghua": 1},
        }

        def fake_author_filter(entries, *_args, **_kwargs):
            self.assertEqual([app.get_arxiv_id(entry) for entry in entries], ["2606.01779"])
            return [kept], author_stats

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(app, "CACHE_REPORT_DIR", str(Path(tmpdir) / "reports")), \
             mock.patch.object(app, "_collect_baseline_entries", return_value=([kept, small], {
                 "scanned": 2,
                 "matched": 2,
                 "filtered_non_cs": 0,
                 "filtered_out_of_window": 0,
             })), \
             mock.patch.object(app, "cache_pdfs_with_stats", return_value=({"2606.01779": "x.pdf"}, cache_stats)), \
             mock.patch.object(app, "filter_candidates_by_author_affiliation", side_effect=fake_author_filter), \
             mock.patch.object(app, "prune_unmatched_cached_pdfs", return_value={
                 "removed_cached_pdfs": 0,
                 "missing_cached_pdfs": 0,
                 "errors": [],
             }):
            result = app.run_pipeline(now=now, target_day=date(2026, 6, 1))

        self.assertEqual([app.get_arxiv_id(entry) for entry in result["ordered_candidates"]], ["2606.01779"])
        self.assertEqual([app.get_arxiv_id(entry) for entry in result["filtered_candidates"]], ["2606.01779"])


if __name__ == "__main__":
    unittest.main()
