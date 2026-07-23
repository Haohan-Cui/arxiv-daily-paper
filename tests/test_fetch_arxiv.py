import sys
import tempfile
import types
import unittest
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

if "feedparser" not in sys.modules:
    sys.modules["feedparser"] = types.SimpleNamespace(parse=lambda *_args, **_kwargs: None)

import fetch_arxiv


class _Feed:
    def __init__(self, entries, items_per_page=None):
        self.entries = entries
        self.feed = {}
        if items_per_page is not None:
            self.feed["opensearch_itemsperpage"] = str(items_per_page)


class _Response:
    def __init__(self, status_code=200, text="<?xml version='1.0'?><feed></feed>", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fetch_arxiv.requests.HTTPError(f"{self.status_code} error")


class FetchArxivTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._state_patch = mock.patch.object(
            fetch_arxiv,
            "_request_state_path",
            Path(self._tmpdir.name) / "arxiv_request_state.json",
        )
        self._legacy_state_patch = mock.patch.object(
            fetch_arxiv,
            "_legacy_request_state_path",
            Path(self._tmpdir.name) / "legacy_arxiv_request_state.json",
        )
        self._state_patch.start()
        self._legacy_state_patch.start()
        self.addCleanup(self._state_patch.stop)
        self.addCleanup(self._legacy_state_patch.stop)

    def test_user_state_dir_prefers_localappdata(self):
        with mock.patch.dict(fetch_arxiv.os.environ, {"LOCALAPPDATA": r"C:\Users\BW\AppData\Local"}, clear=False):
            self.assertEqual(
                fetch_arxiv._user_state_dir(),
                Path(r"C:\Users\BW\AppData\Local") / "DailyPaper",
            )

    def test_read_request_state_merges_legacy_cooldown(self):
        cooldown = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        fetch_arxiv._legacy_request_state_path.parent.mkdir(parents=True, exist_ok=True)
        fetch_arxiv._legacy_request_state_path.write_text(
            f'{{"cooldown_until": "{cooldown}"}}',
            encoding="utf-8",
        )

        self.assertEqual(fetch_arxiv._read_request_state()["cooldown_until"], cooldown)

    def test_query_cs_window_uses_submitted_date_range(self):
        captured = {}

        def fake_get(params):
            captured.update(params)
            return "<?xml version='1.0'?><feed></feed>"

        with mock.patch.object(fetch_arxiv, "_get_with_fallback", side_effect=fake_get), \
             mock.patch.object(fetch_arxiv.feedparser, "parse", return_value=_Feed([])):
            fetch_arxiv.query_cs_window(
                datetime(2026, 5, 28, 4, 0, tzinfo=timezone.utc),
                datetime(2026, 5, 29, 3, 59, tzinfo=timezone.utc),
                start=100,
                max_results=50,
            )

        self.assertEqual(captured["start"], 100)
        self.assertEqual(captured["max_results"], 50)
        self.assertIn("submittedDate:[202605280400 TO 202605290359]", captured["search_query"])
        self.assertIn("cat:cs.*", captured["search_query"])

    def test_iter_recent_cs_has_no_page_count_cap(self):
        page_size = 2
        pages = [
            _Feed([{"id": f"{index}-a"}, {"id": f"{index}-b"}], items_per_page=page_size)
            for index in range(12)
        ]
        pages.append(_Feed([{"id": "last"}], items_per_page=page_size))
        starts = []

        def query(_start_utc, _end_utc, start, max_results):
            starts.append(start)
            self.assertEqual(max_results, page_size)
            return pages.pop(0)

        with mock.patch.object(fetch_arxiv, "MAX_RESULTS_PER_PAGE", page_size), \
             mock.patch.object(fetch_arxiv, "query_cs_window", side_effect=query), \
             mock.patch.object(fetch_arxiv, "_entry_to_dict", side_effect=lambda row: {
                 **row,
                 "published": datetime(2026, 6, 8, 12, tzinfo=timezone.utc),
             }):
            rows = list(fetch_arxiv.iter_recent_cs_single(
                start_utc=datetime(2026, 6, 8, 4, tzinfo=timezone.utc),
                end_utc=datetime(2026, 6, 9, 4, tzinfo=timezone.utc),
            ))

        self.assertEqual(len(rows), 25)
        self.assertEqual(starts, list(range(0, 26, 2)))

    def test_iter_recent_cs_checkpoint_uses_actual_page_size(self):
        checkpoints = []
        rows = [{"id": "a"}, {"id": "b"}]
        with mock.patch.object(fetch_arxiv, "MAX_RESULTS_PER_PAGE", 200), \
             mock.patch.object(fetch_arxiv, "query_cs_sorted", return_value=_Feed(rows)), \
             mock.patch.object(fetch_arxiv, "_entry_to_dict", side_effect=lambda row: {**row, "published": None}):
            list(fetch_arxiv.iter_recent_cs_single(
                start_offset=400,
                on_page_complete=lambda **values: checkpoints.append(values),
            ))

        self.assertEqual(checkpoints[0]["current_start"], 400)
        self.assertEqual(checkpoints[0]["next_start"], 402)

    def test_iter_recent_cs_reduces_page_size_after_503(self):
        calls = []
        progress = []

        def query(_start_utc, _end_utc, start, max_results):
            calls.append((start, max_results))
            if max_results == 2000:
                raise fetch_arxiv.ArxivServiceUnavailableError("503")
            return _Feed([{"id": "a"}], items_per_page=1000)

        with mock.patch.object(fetch_arxiv, "MAX_RESULTS_PER_PAGE", 2000), \
             mock.patch.object(fetch_arxiv, "query_cs_window", side_effect=query), \
             mock.patch.object(fetch_arxiv, "_entry_to_dict", side_effect=lambda row: {
                 **row,
                 "published": datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
             }):
            rows = list(fetch_arxiv.iter_recent_cs_single(
                start_utc=datetime(2026, 6, 15, 4, tzinfo=timezone.utc),
                end_utc=datetime(2026, 6, 16, 4, tzinfo=timezone.utc),
                on_request_progress=progress.append,
            ))

        self.assertEqual([row["id"] for row in rows], ["a"])
        self.assertEqual(calls, [(0, 2000), (0, 1000)])
        self.assertTrue(any("503" in message and "max_results=2000" in message for message in progress))

    def test_iter_recent_cs_queries_categories_and_deduplicates(self):
        calls = []
        rows_by_category = {
            "cs.CL": _Feed([{"id": "http://arxiv.org/abs/1"}], items_per_page=500),
            "cs.LG": _Feed([{"id": "http://arxiv.org/abs/1"}, {"id": "http://arxiv.org/abs/2"}], items_per_page=500),
        }

        def query(category, _start_utc, _end_utc, start, max_results):
            calls.append((category, start, max_results))
            return rows_by_category[category]

        with mock.patch.object(fetch_arxiv, "ARXIV_PRIMARY_CATEGORY_PREFIXES", ["cs.CL", "cs.LG"]), \
             mock.patch.object(fetch_arxiv, "MAX_RESULTS_PER_PAGE", 500), \
             mock.patch.object(fetch_arxiv, "query_category_window", side_effect=query), \
             mock.patch.object(fetch_arxiv, "_entry_to_dict", side_effect=lambda row: {
                 **row,
                 "published": datetime(2026, 6, 23, 12, tzinfo=timezone.utc),
             }):
            rows = list(fetch_arxiv.iter_recent_cs(
                start_utc=datetime(2026, 6, 23, 4, tzinfo=timezone.utc),
                end_utc=datetime(2026, 6, 24, 4, tzinfo=timezone.utc),
            ))

        self.assertEqual([row["id"] for row in rows], ["http://arxiv.org/abs/1", "http://arxiv.org/abs/2"])
        self.assertEqual([call[0] for call in calls], ["cs.CL", "cs.LG"])

    def test_iter_recent_cs_category_continues_past_100_when_server_pages_at_100(self):
        calls = []
        pages = {
            ("cs.CL", 0): _Feed(
                [{"id": f"http://arxiv.org/abs/{index}"} for index in range(100)],
                items_per_page=100,
            ),
            ("cs.CL", 100): _Feed(
                [{"id": f"http://arxiv.org/abs/{index}"} for index in range(100, 150)],
                items_per_page=100,
            ),
        }

        def query(category, _start_utc, _end_utc, start, max_results):
            calls.append((category, start, max_results))
            return pages.get((category, start), _Feed([], items_per_page=100))

        with mock.patch.object(fetch_arxiv, "ARXIV_PRIMARY_CATEGORY_PREFIXES", ["cs.CL"]), \
             mock.patch.object(fetch_arxiv, "MAX_RESULTS_PER_PAGE", 500), \
             mock.patch.object(fetch_arxiv, "query_category_window", side_effect=query), \
             mock.patch.object(fetch_arxiv, "_entry_to_dict", side_effect=lambda row: {
                 **row,
                 "published": datetime(2026, 6, 23, 12, tzinfo=timezone.utc),
             }):
            rows = list(fetch_arxiv.iter_recent_cs(
                start_utc=datetime(2026, 6, 23, 4, tzinfo=timezone.utc),
                end_utc=datetime(2026, 6, 24, 4, tzinfo=timezone.utc),
            ))

        self.assertEqual(len(rows), 150)
        self.assertEqual([call[1] for call in calls], [0, 100])

    def test_iter_recent_cs_category_continues_until_empty_when_page_size_unknown(self):
        calls = []
        pages = {
            ("cs.CL", 0): _Feed([{"id": f"http://arxiv.org/abs/{index}"} for index in range(100)]),
            ("cs.CL", 100): _Feed([{"id": f"http://arxiv.org/abs/{index}"} for index in range(100, 120)]),
            ("cs.CL", 120): _Feed([]),
        }

        def query(category, _start_utc, _end_utc, start, max_results):
            calls.append((category, start, max_results))
            return pages[(category, start)]

        with mock.patch.object(fetch_arxiv, "ARXIV_PRIMARY_CATEGORY_PREFIXES", ["cs.CL"]), \
             mock.patch.object(fetch_arxiv, "MAX_RESULTS_PER_PAGE", 500), \
             mock.patch.object(fetch_arxiv, "query_category_window", side_effect=query), \
             mock.patch.object(fetch_arxiv, "_entry_to_dict", side_effect=lambda row: {
                 **row,
                 "published": datetime(2026, 6, 23, 12, tzinfo=timezone.utc),
             }):
            rows = list(fetch_arxiv.iter_recent_cs(
                start_utc=datetime(2026, 6, 23, 4, tzinfo=timezone.utc),
                end_utc=datetime(2026, 6, 24, 4, tzinfo=timezone.utc),
            ))

        self.assertEqual(len(rows), 120)
        self.assertEqual([call[1] for call in calls], [0, 100, 120])

    def test_iter_recent_cs_raises_when_all_adaptive_page_sizes_503(self):
        with mock.patch.object(fetch_arxiv, "MAX_RESULTS_PER_PAGE", 2000), \
             mock.patch.object(fetch_arxiv, "query_cs_window", side_effect=fetch_arxiv.ArxivServiceUnavailableError("503")):
            with self.assertRaises(fetch_arxiv.ArxivServiceUnavailableError):
                list(fetch_arxiv.iter_recent_cs_single(
                    start_utc=datetime(2026, 6, 15, 4, tzinfo=timezone.utc),
                    end_utc=datetime(2026, 6, 16, 4, tzinfo=timezone.utc),
                ))

    def test_reserve_request_slot_is_global_across_arxiv_hosts(self):
        original_window = fetch_arxiv._request_start_window
        original_last = fetch_arxiv._last_request_start_ts
        fetch_arxiv._request_start_window = deque()
        fetch_arxiv._last_request_start_ts = 0.0
        sleeps = []
        try:
            with mock.patch.object(fetch_arxiv, "RATE_LIMIT_MIN_INTERVAL_SEC", 3.1), \
                 mock.patch.object(fetch_arxiv, "SESSION_RATE_LIMIT_PER_MIN", 18), \
                 mock.patch.object(fetch_arxiv, "_persisted_last_request_gap", return_value=None), \
                 mock.patch.object(fetch_arxiv.time, "monotonic", side_effect=[10.0, 11.0, 13.2]), \
                 mock.patch.object(fetch_arxiv.time, "sleep", side_effect=sleeps.append):
                fetch_arxiv._reserve_request_slot("https://arxiv.org/api/query")
                fetch_arxiv._reserve_request_slot("https://export.arxiv.org/pdf/2606.00001.pdf")
        finally:
            fetch_arxiv._request_start_window = original_window
            fetch_arxiv._last_request_start_ts = original_last

        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 2.1)

    def test_reserve_request_slot_enforces_persisted_restart_gap(self):
        fetch_arxiv._write_request_state({
            "last_request_started_at": datetime.now(timezone.utc).isoformat(),
        })
        sleeps = []
        with mock.patch.object(fetch_arxiv, "RATE_LIMIT_MIN_INTERVAL_SEC", 3.1), \
             mock.patch.object(fetch_arxiv, "SESSION_RATE_LIMIT_PER_MIN", 18), \
             mock.patch.object(fetch_arxiv, "_persisted_last_request_gap", side_effect=[0.1, 3.2]), \
             mock.patch.object(fetch_arxiv.time, "monotonic", side_effect=[10.0, 13.2]), \
             mock.patch.object(fetch_arxiv.time, "sleep", side_effect=sleeps.append):
            fetch_arxiv._reserve_request_slot("https://export.arxiv.org/api/query")
        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)

    def test_guarded_get_does_not_add_post_request_sleep(self):
        session = mock.Mock()
        session.get.return_value = object()
        with mock.patch.object(fetch_arxiv, "_reserve_request_slot"), \
             mock.patch.object(fetch_arxiv.time, "sleep") as sleep_mock:
            fetch_arxiv._guarded_get(session, "https://arxiv.org/api/query", stream=True)
        sleep_mock.assert_not_called()
        session.get.assert_called_once_with(
            "https://arxiv.org/api/query",
            params=None,
            timeout=fetch_arxiv.REQUEST_TIMEOUT,
            stream=True,
        )

    def test_retry_adapter_has_no_hidden_retries(self):
        session = fetch_arxiv._build_session()
        self.assertEqual(session.get_adapter("https://").max_retries.total, 0)

    def test_request_with_network_fallback_forces_proxy_for_api(self):
        proxy_response = object()
        proxy_session = object()
        with mock.patch.object(fetch_arxiv, "ARXIV_API_USE_PROXY", True), \
             mock.patch.object(fetch_arxiv, "_HAS_PROXY_FALLBACK", True), \
             mock.patch.object(fetch_arxiv, "_PROXY_SESSION", proxy_session), \
             mock.patch.object(fetch_arxiv, "_guarded_get", return_value=proxy_response) as guarded_get:
            result = fetch_arxiv.request_with_network_fallback(
                "https://export.arxiv.org/api/query",
                params={"a": "b"},
                timeout=(1, 1),
            )
        self.assertIs(result, proxy_response)
        guarded_get.assert_called_once_with(
            proxy_session,
            "https://export.arxiv.org/api/query",
            params={"a": "b"},
            timeout=(1, 1),
            stream=False,
        )

    def test_request_with_network_fallback_uses_direct_for_arxiv_pdf(self):
        direct_response = object()
        direct_session = object()
        with mock.patch.object(fetch_arxiv, "_HAS_PROXY_FALLBACK", True), \
             mock.patch.object(fetch_arxiv, "_DIRECT_SESSION", direct_session), \
             mock.patch.object(fetch_arxiv, "_guarded_get", return_value=direct_response) as guarded_get:
            result = fetch_arxiv.request_with_network_fallback(
                "https://arxiv.org/pdf/2607.13027v1.pdf",
                timeout=(1, 1),
                stream=True,
            )
        self.assertIs(result, direct_response)
        guarded_get.assert_called_once_with(
            direct_session,
            "https://arxiv.org/pdf/2607.13027v1.pdf",
            params=None,
            timeout=(1, 1),
            stream=True,
        )

    def test_iter_pdf_urls_prefers_extensionless_official_shape_before_legacy_pdf_suffix(self):
        self.assertEqual(
            list(fetch_arxiv.iter_pdf_urls("2607.13027v1"))[:4],
            [
                "https://arxiv.org/pdf/2607.13027v1",
                "https://arxiv.org/pdf/2607.13027v1.pdf",
                "https://arxiv.org/pdf/2607.13027",
                "https://arxiv.org/pdf/2607.13027.pdf",
            ],
        )

    def test_get_with_fallback_stops_immediately_on_429(self):
        response = _Response(status_code=429, text="Rate exceeded.", headers={"Retry-After": "5"})
        with mock.patch.object(fetch_arxiv, "request_with_network_fallback", return_value=response) as request:
            with self.assertRaises(fetch_arxiv.ArxivRateLimitError):
                fetch_arxiv._get_with_fallback({"search_query": "cat:cs.AI"})
        self.assertEqual(request.call_count, 1)

    def test_get_with_fallback_turns_503_into_service_unavailable(self):
        response = _Response(status_code=503, text="Service Unavailable")
        with mock.patch.object(fetch_arxiv, "request_with_network_fallback", return_value=response):
            with self.assertRaises(fetch_arxiv.ArxivServiceUnavailableError) as ctx:
                fetch_arxiv._get_with_fallback({"search_query": "cat:cs.AI"})
        self.assertIn("HTTP 503", str(ctx.exception))

    def test_get_with_fallback_persists_429_cooldown(self):
        response = _Response(status_code=429, text="Rate exceeded.")
        with mock.patch.object(fetch_arxiv, "ARXIV_429_COOLDOWN_SEC", 60), \
             mock.patch.object(fetch_arxiv, "request_with_network_fallback", return_value=response):
            with self.assertRaises(fetch_arxiv.ArxivRateLimitError) as ctx:
                fetch_arxiv._get_with_fallback({"search_query": "cat:cs.AI"})
        state = fetch_arxiv._read_request_state()
        self.assertIn("cooldown_until", state)
        self.assertIn("cooldown_until", str(ctx.exception))

    def test_429_cooldown_escalates_for_consecutive_errors(self):
        response = _Response(status_code=429, text="Rate exceeded.")
        with mock.patch.object(fetch_arxiv, "ARXIV_429_COOLDOWN_SEC", 3600), \
             mock.patch.object(fetch_arxiv, "ARXIV_429_COOLDOWN_MAX_SEC", 21600):
            before_first = datetime.now(timezone.utc)
            first_until = fetch_arxiv._cooldown_until_from_response(response)
            fetch_arxiv._write_request_state({"consecutive_429": 1})
            before_second = datetime.now(timezone.utc)
            second_until = fetch_arxiv._cooldown_until_from_response(response)

        self.assertGreaterEqual((first_until - before_first).total_seconds(), 3599)
        self.assertLessEqual((first_until - before_first).total_seconds(), 3601)
        self.assertGreaterEqual((second_until - before_second).total_seconds(), 7199)
        self.assertLessEqual((second_until - before_second).total_seconds(), 7201)

    def test_persisted_cooldown_blocks_before_request(self):
        fetch_arxiv._write_request_state({
            "cooldown_until": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(),
        })
        with self.assertRaises(fetch_arxiv.ArxivRateLimitError) as ctx:
            fetch_arxiv._reserve_request_slot("https://export.arxiv.org/api/query")
        self.assertIn("cooldown active", str(ctx.exception))

    def test_reserve_request_slot_preserves_expired_cooldown_until_success(self):
        expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        fetch_arxiv._write_request_state({"cooldown_until": expired, "consecutive_429": 2})
        with mock.patch.object(fetch_arxiv, "RATE_LIMIT_MIN_INTERVAL_SEC", 0), \
             mock.patch.object(fetch_arxiv, "SESSION_RATE_LIMIT_PER_MIN", 18), \
             mock.patch.object(fetch_arxiv, "_persisted_last_request_gap", return_value=None):
            fetch_arxiv._reserve_request_slot("https://export.arxiv.org/api/query")
        state = fetch_arxiv._read_request_state()
        self.assertEqual(state["cooldown_until"], expired)
        self.assertEqual(state["consecutive_429"], 2)

    def test_validate_api_payload_rejects_html(self):
        with self.assertRaises(ValueError):
            fetch_arxiv._validate_api_payload("<html>proxy login</html>")


if __name__ == "__main__":
    unittest.main()
