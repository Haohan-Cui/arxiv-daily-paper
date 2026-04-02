from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from requests.exceptions import HTTPError

from config import CONNECT_TIMEOUT_SEC, PDF_CACHE_DIR, READ_TIMEOUT_SEC
from fetch_arxiv import get_arxiv_id, iter_pdf_urls, request_with_network_fallback
from runtime_control import PipelineController

SAFE_NAME = re.compile(r"[^a-zA-Z0-9._/-]+")
ProgressCallback = Callable[[str, str, str, float | None], None]


def ensure_dir(p: str | Path):
    Path(p).mkdir(parents=True, exist_ok=True)


def _emit_progress(callback: ProgressCallback | None, stage: str, message: str, state: str = "info", percent: float | None = None) -> None:
    if callback:
        callback(stage, message, state, percent)


def cache_pdfs(entries: List[Dict[str, Any]], report_date: str | None = None) -> Dict[str, str]:
    cached, _stats = cache_pdfs_with_stats(entries, report_date=report_date)
    return cached


def cache_pdfs_with_stats(
    entries: List[Dict[str, Any]],
    report_date: str | None = None,
    controller: PipelineController | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    cache_dir = Path(PDF_CACHE_DIR) / report_date if report_date else Path(PDF_CACHE_DIR)
    ensure_dir(cache_dir)
    out: Dict[str, str] = {}
    stats: Dict[str, Any] = {
        "attempted": len(entries),
        "cache_hits": 0,
        "downloaded": 0,
        "failed": 0,
        "errors": [],
        "cache_dir": str(cache_dir),
    }

    total = len(entries) or 1
    for index, entry in enumerate(entries, start=1):
        if controller:
            controller.checkpoint()
        aid = get_arxiv_id(entry)
        percent = index / total * 100.0
        _emit_progress(progress_callback, "pdf_cache", f"???? PDF {index}/{len(entries)}: {aid}", "running", percent)
        rel = SAFE_NAME.sub("_", aid) + ".pdf"
        fpath = cache_dir / rel
        if fpath.exists():
            out[aid] = str(fpath)
            stats["cache_hits"] += 1
            _emit_progress(progress_callback, "pdf_cache", f"????: {aid}", "running", percent)
            continue

        last_err = None
        for url in iter_pdf_urls(aid):
            if controller:
                controller.checkpoint()
            try:
                response = request_with_network_fallback(url, timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC))
                response.raise_for_status()
                with open(fpath, "wb") as handle:
                    handle.write(response.content)
                out[aid] = str(fpath)
                stats["downloaded"] += 1
                _emit_progress(progress_callback, "pdf_cache", f"???: {aid}", "running", percent)
                break
            except HTTPError as exc:
                last_err = exc
                if exc.response is not None and exc.response.status_code == 404:
                    continue
                continue
            except Exception as exc:
                last_err = exc
                continue

        if aid not in out:
            message = f"cache failed for {aid}: {last_err}"
            stats["failed"] += 1
            stats["errors"].append(message)
            print(f"[WARN] {message}")
            _emit_progress(progress_callback, "pdf_cache", f"????: {aid}", "warning", percent)

    return out, stats
