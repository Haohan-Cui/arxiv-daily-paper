from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

from requests.exceptions import HTTPError

from config import CONNECT_TIMEOUT_SEC, MIN_PDF_BYTES, PDF_CACHE_DIR, READ_TIMEOUT_SEC
from fetch_arxiv import extract_pdf_url, get_arxiv_id, iter_pdf_urls, request_with_network_fallback
from runtime_control import PipelineController

SAFE_NAME = re.compile(r"[^a-zA-Z0-9._/-]+")
ProgressCallback = Callable[[str, str, str, float | None], None]


def ensure_dir(p: str | Path):
    Path(p).mkdir(parents=True, exist_ok=True)


def _emit_progress(callback: ProgressCallback | None, stage: str, message: str, state: str = "info", percent: float | None = None) -> None:
    if callback:
        callback(stage, message, state, percent)


def _content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Content-Length") or headers.get("content-length")
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else None
    except Exception:
        return None


def _format_download_error(url: str, exc: Exception | None) -> str:
    if exc is None:
        return f"{url}: no response"
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status is not None:
        return f"{url}: HTTP {status} ({exc})"
    return f"{url}: {type(exc).__name__}: {exc}"


def _candidate_pdf_urls(entry: Dict[str, Any], aid: str):
    seen = set()
    official_url = extract_pdf_url(entry)
    if official_url:
        seen.add(official_url)
        yield official_url
    for url in iter_pdf_urls(aid):
        if url not in seen:
            seen.add(url)
            yield url


def _base_arxiv_id(aid: str) -> str:
    return aid.rsplit("v", 1)[0] if "v" in aid else aid


def _candidate_download_urls(entry: Dict[str, Any], aid: str) -> Iterable[Tuple[str, str]]:
    for url in _candidate_pdf_urls(entry, aid):
        yield url, "pdf"
    yield f"https://arxiv.org/html/{_base_arxiv_id(aid)}", "html"


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
        "skipped_small": 0,
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
        _emit_progress(progress_callback, "pdf_cache", f"正在缓存 PDF {index}/{len(entries)}: {aid}", "running", percent)
        rel = SAFE_NAME.sub("_", aid) + ".pdf"
        fpath = cache_dir / rel
        html_path = fpath.with_suffix(".html")
        if fpath.exists():
            existing_size = fpath.stat().st_size
            if existing_size < MIN_PDF_BYTES:
                stats["skipped_small"] += 1
                try:
                    fpath.unlink()
                except Exception:
                    pass
                _emit_progress(
                    progress_callback,
                    "pdf_cache",
                    f"跳过小于1MB的PDF缓存: {aid} ({existing_size} bytes)",
                    "warning",
                    percent,
                )
                continue
            out[aid] = str(fpath)
            stats["cache_hits"] += 1
            _emit_progress(progress_callback, "pdf_cache", f"缓存命中: {aid}", "running", percent)
            continue
        if html_path.exists():
            out[aid] = str(html_path)
            stats["cache_hits"] += 1
            _emit_progress(progress_callback, "pdf_cache", f"HTML fallback 缓存命中: {aid}", "running", percent)
            continue

        last_err = None
        last_url = None
        errors_seen: List[str] = []
        skipped_small = False
        for url, document_type in _candidate_download_urls(entry, aid):
            last_url = url
            if controller:
                controller.checkpoint()
            try:
                current_path = fpath if document_type == "pdf" else fpath.with_suffix(".html")
                response = request_with_network_fallback(
                    url,
                    timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC),
                    stream=True,
                )
                response.raise_for_status()
                content_length = _content_length(response)
                if document_type == "pdf" and content_length is not None and content_length < MIN_PDF_BYTES:
                    stats["skipped_small"] += 1
                    skipped_small = True
                    _emit_progress(
                        progress_callback,
                        "pdf_cache",
                        f"跳过小于1MB的PDF: {aid} ({content_length} bytes)",
                        "warning",
                        percent,
                    )
                    break
                temp_path = current_path.with_suffix(f"{current_path.suffix}.part")
                bytes_written = 0
                with open(temp_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if controller:
                            controller.checkpoint()
                        if chunk:
                            bytes_written += len(chunk)
                            handle.write(chunk)
                if document_type == "pdf" and bytes_written < MIN_PDF_BYTES:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    stats["skipped_small"] += 1
                    skipped_small = True
                    _emit_progress(
                        progress_callback,
                        "pdf_cache",
                        f"跳过小于1MB的PDF: {aid} ({bytes_written} bytes)",
                        "warning",
                        percent,
                    )
                    break
                temp_path.replace(current_path)
                out[aid] = str(current_path)
                stats["downloaded"] += 1
                label = "HTML fallback 下载完成" if document_type == "html" else "下载完成"
                _emit_progress(progress_callback, "pdf_cache", f"{label}: {aid}", "running", percent)
                break
            except HTTPError as exc:
                last_err = exc
                errors_seen.append(_format_download_error(url, exc))
                if exc.response is not None and exc.response.status_code == 404:
                    continue
                continue
            except Exception as exc:
                last_err = exc
                errors_seen.append(_format_download_error(url, exc))
                try:
                    fpath.with_suffix(f"{fpath.suffix}.part").unlink(missing_ok=True)
                    fpath.with_suffix(".html.part").unlink(missing_ok=True)
                except Exception:
                    pass
                continue

        if aid not in out and not skipped_small:
            detail = "; ".join(errors_seen) if errors_seen else _format_download_error(last_url or "-", last_err)
            message = f"cache failed for {aid}: {detail}"
            stats["failed"] += 1
            stats["errors"].append(message)
            print(f"[WARN] {message}")
            _emit_progress(progress_callback, "pdf_cache", f"缓存失败: {aid} ({message})", "warning", percent)

    return out, stats
