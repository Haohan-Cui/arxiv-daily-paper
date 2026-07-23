import tempfile
import unittest
from pathlib import Path
from unittest import mock

import prefetch
from runtime_control import PipelineCancelled, PipelineController


class _Response:
    def __init__(self, content=b"pdf-data", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        yield self.content[:3]
        yield self.content[3:]


class PrefetchTest(unittest.TestCase):
    def test_cache_pdfs_with_stats_tracks_downloads_and_failures(self):
        entries = [
            {"id": "http://arxiv.org/abs/1234.5678v1"},
            {"id": "http://arxiv.org/abs/9999.0001v1"},
        ]
        responses = [_Response(), RuntimeError("dns failure")]

        def fake_request(url, timeout=None, stream=False):
            self.assertTrue(stream)
            response = responses.pop(0) if responses else RuntimeError("dns failure")
            if isinstance(response, Exception):
                raise response
            return response

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "MIN_PDF_BYTES", 1), \
             mock.patch.object(prefetch, "request_with_network_fallback", side_effect=fake_request), \
             mock.patch.object(prefetch, "iter_pdf_urls", side_effect=lambda aid: [f"https://example/{aid}.pdf"]):
            cached, stats = prefetch.cache_pdfs_with_stats(entries, report_date="2026-03-31")

            self.assertIn("1234.5678v1", cached)
            self.assertNotIn("9999.0001v1", cached)
            self.assertEqual(stats["attempted"], 2)
            self.assertEqual(stats["downloaded"], 1)
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(len(stats["errors"]), 1)
            self.assertIn("RuntimeError: dns failure", stats["errors"][0])
            self.assertIn("https://example/9999.0001v1.pdf", stats["errors"][0])
            self.assertIn("2026-03-31", stats["cache_dir"])
            self.assertTrue(Path(cached["1234.5678v1"]).exists())
            self.assertIn("2026-03-31", cached["1234.5678v1"])

    def test_cache_pdfs_with_stats_prefers_official_pdf_link_from_entry(self):
        entry = {
            "id": "http://arxiv.org/abs/1234.5678v1",
            "links": [
                {"title": "pdf", "type": "application/pdf", "href": "https://arxiv.org/pdf/1234.5678v1"},
            ],
        }
        seen_urls = []

        def fake_request(url, timeout=None, stream=False):
            seen_urls.append(url)
            return _Response(content=b"x" * 20)

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "MIN_PDF_BYTES", 1), \
             mock.patch.object(prefetch, "request_with_network_fallback", side_effect=fake_request):
            cached, stats = prefetch.cache_pdfs_with_stats([entry], report_date="2026-03-31")

        self.assertIn("1234.5678v1", cached)
        self.assertEqual(seen_urls, ["https://arxiv.org/pdf/1234.5678v1"])

    def test_cache_pdfs_with_stats_falls_back_to_html_when_pdf_urls_fail(self):
        entry = {"id": "http://arxiv.org/abs/2607.13027v1"}
        seen_urls = []

        def fake_request(url, timeout=None, stream=False):
            seen_urls.append(url)
            if "/html/" in url:
                return _Response(content=b"<html>PalmClaw</html>", headers={"Content-Type": "text/html"})
            raise RuntimeError("404")

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "MIN_PDF_BYTES", 100), \
             mock.patch.object(prefetch, "request_with_network_fallback", side_effect=fake_request):
            cached, stats = prefetch.cache_pdfs_with_stats([entry], report_date="2026-07-14")

            self.assertTrue(cached["2607.13027v1"].endswith(".html"))
            self.assertTrue(Path(cached["2607.13027v1"]).exists())
            self.assertEqual(stats["downloaded"], 1)
            self.assertIn("https://arxiv.org/html/2607.13027", seen_urls)

    def test_cache_pdfs_with_stats_counts_html_fallback_cache_hit(self):
        entry = {"id": "http://arxiv.org/abs/2607.13027v1"}

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir):
            cache_dir = Path(tmpdir) / "2026-07-14"
            cache_dir.mkdir(parents=True, exist_ok=True)
            existing = cache_dir / "2607.13027v1.html"
            existing.write_text("<html></html>", encoding="utf-8")
            cached, stats = prefetch.cache_pdfs_with_stats([entry], report_date="2026-07-14")

        self.assertEqual(cached["2607.13027v1"], str(existing))
        self.assertEqual(stats["cache_hits"], 1)

    def test_cache_pdfs_with_stats_counts_cache_hits(self):
        entry = {"id": "http://arxiv.org/abs/1234.5678v1"}

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "MIN_PDF_BYTES", 1):
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

    def test_cache_pdfs_with_stats_skips_small_content_length_without_download(self):
        entry = {"id": "http://arxiv.org/abs/1234.5678v1"}
        response = _Response(content=b"x" * 20, headers={"Content-Length": "20"})
        response.iter_content = mock.Mock(side_effect=response.iter_content)

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "MIN_PDF_BYTES", 100), \
             mock.patch.object(prefetch, "request_with_network_fallback", return_value=response), \
             mock.patch.object(prefetch, "iter_pdf_urls", return_value=["https://example/1234.5678v1.pdf"]):
            cached, stats = prefetch.cache_pdfs_with_stats([entry], report_date="2026-03-31")

        self.assertEqual(cached, {})
        self.assertEqual(stats["skipped_small"], 1)
        response.iter_content.assert_not_called()

    def test_cache_pdfs_with_stats_discards_small_download_without_length(self):
        entry = {"id": "http://arxiv.org/abs/1234.5678v1"}

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "MIN_PDF_BYTES", 100), \
             mock.patch.object(prefetch, "request_with_network_fallback", return_value=_Response(content=b"x" * 20)), \
             mock.patch.object(prefetch, "iter_pdf_urls", return_value=["https://example/1234.5678v1.pdf"]):
            cached, stats = prefetch.cache_pdfs_with_stats([entry], report_date="2026-03-31")

            self.assertEqual(cached, {})
            self.assertEqual(stats["skipped_small"], 1)
            self.assertFalse(any((Path(tmpdir) / "2026-03-31").glob("*.pdf")))

    def test_cache_pdfs_with_stats_removes_small_existing_cache(self):
        entry = {"id": "http://arxiv.org/abs/1234.5678v1"}

        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(prefetch, "PDF_CACHE_DIR", tmpdir), \
             mock.patch.object(prefetch, "MIN_PDF_BYTES", 100):
            cache_dir = Path(tmpdir) / "2026-03-31"
            cache_dir.mkdir(parents=True, exist_ok=True)
            existing = cache_dir / "1234.5678v1.pdf"
            existing.write_bytes(b"tiny")
            cached, stats = prefetch.cache_pdfs_with_stats([entry], report_date="2026-03-31")

            self.assertEqual(cached, {})
            self.assertEqual(stats["skipped_small"], 1)
            self.assertFalse(existing.exists())


if __name__ == "__main__":
    unittest.main()
