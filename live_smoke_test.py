from __future__ import annotations

import json
import time
from pathlib import Path

from fetch_arxiv import _get_with_fallback, iter_pdf_urls, request_with_network_fallback


def run_live_smoke() -> dict:
    result = {"api": {}, "pdf": {}, "ok": False}

    api_start = time.perf_counter()
    xml = _get_with_fallback(
        {
            "search_query": "cat:cs.AI",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": 1,
        }
    )
    result["api"] = {
        "latency_sec": round(time.perf_counter() - api_start, 3),
        "payload_prefix": xml[:120],
        "payload_size": len(xml),
    }

    pdf_url = next(iter(iter_pdf_urls("2501.00001v1")))
    pdf_start = time.perf_counter()
    response = request_with_network_fallback(pdf_url, timeout=(20, 60))
    response.raise_for_status()
    result["pdf"] = {
        "url": pdf_url,
        "latency_sec": round(time.perf_counter() - pdf_start, 3),
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content_size": len(response.content),
    }
    result["ok"] = True
    return result


if __name__ == "__main__":
    payload = run_live_smoke()
    out = Path("cache_pdfs") / "_reports" / "live_smoke_test.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"wrote {out}")
