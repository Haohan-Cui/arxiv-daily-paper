import tempfile
import unittest
from pathlib import Path
from unittest import mock

import prefetch
from runtime_control import PipelineCancelled, PipelineController


class _Response:
    def __init__(self, content=b"pdf-data", status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class PrefetchTest(unittest.TestCase):
    def test_cache_pdfs_with_stats_tracks_downloads_and_failures(self):
        entries = [
            {"id": "http://arxiv.org/abs/1234.5678v1"},
            {"id": "http://arxiv.org/abs/9999.0001v1"},
        ]
        responses = [_Response(), RuntimeError("dns failure")]

        def fake_request(url, timeout=None):
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "request_with_network_fallback", side_effect=fake_request), \
             mock.patch.object(prefetch, "iter_pdf_urls", side_effect=lambda aid: [f"https://example/{aid}.pdf"]):
            cached, stats = prefetch.cache_pdfs_with_stats(entries, report_date="2026-03-31")

            self.assertIn("1234.5678v1", cached)
            self.assertNotIn("9999.0001v1", cached)
            self.assertEqual(stats["attempted"], 2)
            self.assertEqual(stats["downloaded"], 1)
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(len(stats["errors"]), 1)
            self.assertIn("2026-03-31", stats["cache_dir"])
            self.assertTrue(Path(cached["1234.5678v1"]).exists())
            self.assertIn("2026-03-31", cached["1234.5678v1"])

    def test_cache_pdfs_with_stats_counts_cache_hits(self):
        entry = {"id": "http://arxiv.org/abs/1234.5678v1"}

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir):
            cache_dir = Path(tmpdir) / "2026-03-31"
            cache_dir.mkdir(parents=True, exist_ok=True)
            existing = cache_dir / "1234.5678v1.pdf"
            existing.write_bytes(b"already-there")
            cached, stats = prefetch.cache_pdfs_with_stats([entry], report_date="2026-03-31")

            self.assertEqual(stats["cache_hits"], 1)
            self.assertEqual(stats["downloaded"], 0)
            self.assertEqual(cached["1234.5678v1"], str(existing))

    def test_cache_pdfs_with_stats_honors_cancellation(self):
        controller = PipelineController()
        controller.cancel()
        with self.assertRaises(PipelineCancelled):
            prefetch.cache_pdfs_with_stats([
                {"id": "http://arxiv.org/abs/1234.5678v1"}
            ], controller=controller)


if __name__ == "__main__":
    unittest.main()
