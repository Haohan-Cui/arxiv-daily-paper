from __future__ import annotations

import os
import json
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

import feedparser
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ProxyError, SSLError

from config import (
    ARXIV_API_ENDPOINTS,
    ARXIV_API_USE_PROXY,
    ARXIV_429_COOLDOWN_MAX_SEC,
    ARXIV_429_COOLDOWN_SEC,
    ARXIV_PRIMARY_CATEGORY_PREFIXES,
    CACHE_REPORT_DIR,
    DEBUG,
    MAX_RESULTS_PER_PAGE,
    NO_PROXY_HOSTS,
    PROXIES,
    RATE_LIMIT_MIN_INTERVAL_SEC,
    REQUESTS_UA,
    REQUEST_CONCURRENCY_LIMIT,
    REQUEST_TIMEOUT,
    RESPECT_ENV_PROXIES,
    SESSION_RATE_LIMIT_PER_MIN,
)

PDF_ENDPOINTS = [
    "https://arxiv.org/pdf",
    "https://export.arxiv.org/pdf",
]

_request_semaphore = threading.BoundedSemaphore(max(1, REQUEST_CONCURRENCY_LIMIT))
_request_slot_lock = threading.Lock()
_request_start_window: deque[float] = deque()
_last_request_start_ts = 0.0
def _user_state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "DailyPaper"
    return Path.home() / ".dailypaper"


_request_state_path = _user_state_dir() / "arxiv_request_state.json"
_legacy_request_state_path = Path(CACHE_REPORT_DIR) / "arxiv_request_state.json"


class ArxivRateLimitError(RuntimeError):
    pass


class ArxivServiceUnavailableError(RuntimeError):
    pass


def _candidate_request_state_paths() -> list[Path]:
    paths = [_request_state_path, _legacy_request_state_path]
    try:
        executable_dir = Path(sys.executable).resolve().parent
        paths.append(executable_dir / "cache_pdfs" / "_reports" / "arxiv_request_state.json")
    except Exception:
        pass

    deduped: list[Path] = []
    seen = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def _read_json_file(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _max_iso_datetime(values: list[str]) -> str | None:
    best_dt: datetime | None = None
    best_raw: str | None = None
    for value in values:
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
        except Exception:
            continue
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best_raw = dt.isoformat()
    return best_raw


def _read_request_state() -> Dict[str, Any]:
    payloads = [_read_json_file(path) for path in _candidate_request_state_paths()]
    payloads = [payload for payload in payloads if payload]
    if not payloads:
        return {}
    merged: Dict[str, Any] = {}
    latest_request = _max_iso_datetime([
        str(payload.get("last_request_started_at")) for payload in payloads if payload.get("last_request_started_at")
    ])
    latest_cooldown = _max_iso_datetime([
        str(payload.get("cooldown_until")) for payload in payloads if payload.get("cooldown_until")
    ])
    latest_429 = _max_iso_datetime([
        str(payload.get("last_429_at")) for payload in payloads if payload.get("last_429_at")
    ])
    if latest_request:
        merged["last_request_started_at"] = latest_request
    if latest_cooldown:
        merged["cooldown_until"] = latest_cooldown
    if latest_429:
        merged["last_429_at"] = latest_429
    consecutive_values = []
    for payload in payloads:
        try:
            consecutive_values.append(int(payload.get("consecutive_429", 0) or 0))
        except Exception:
            pass
    if consecutive_values:
        merged["consecutive_429"] = max(consecutive_values)
    for payload in payloads:
        if payload.get("last_429_endpoint"):
            merged["last_429_endpoint"] = payload["last_429_endpoint"]
    return merged


def _write_request_state(payload: Dict[str, Any]) -> None:
    wrote = False
    for path in (_request_state_path, _legacy_request_state_path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            wrote = True
        except Exception:
            if DEBUG:
                print(f"[WARN] failed to persist arXiv request state at {path}")
    if not wrote and DEBUG:
        print("[WARN] failed to persist arXiv request state")


def describe_arxiv_request_state() -> Dict[str, Any]:
    state = _read_request_state()
    proxy_values = sorted({value for value in (PROXIES or {}).values() if value})
    return {
        "api_endpoints": list(ARXIV_API_ENDPOINTS),
        "api_proxy_forced": bool(ARXIV_API_USE_PROXY),
        "proxy_configured": bool(_HAS_PROXY_FALLBACK),
        "proxy_values": proxy_values,
        "state_file": str(_request_state_path),
        "legacy_state_file": str(_legacy_request_state_path),
        "cooldown_until": state.get("cooldown_until"),
        "last_429_at": state.get("last_429_at"),
        "consecutive_429": int(state.get("consecutive_429", 0) or 0),
    }


def _parse_retry_after(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return datetime.now(timezone.utc) + timedelta(seconds=max(0, int(value)))
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _cooldown_until_from_response(response: requests.Response) -> datetime:
    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
    if retry_after:
        return retry_after
    state = _read_request_state()
    consecutive = int(state.get("consecutive_429", 0) or 0) + 1
    cooldown_seconds = min(
        max(1, ARXIV_429_COOLDOWN_SEC) * (2 ** max(0, consecutive - 1)),
        max(1, ARXIV_429_COOLDOWN_MAX_SEC),
    )
    return datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)


def _check_persisted_cooldown() -> None:
    cooldown_until = _read_request_state().get("cooldown_until")
    if not cooldown_until:
        return
    try:
        until = datetime.fromisoformat(cooldown_until)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        until = until.astimezone(timezone.utc)
    except Exception:
        return
    now = datetime.now(timezone.utc)
    if now < until:
        wait_seconds = int((until - now).total_seconds())
        raise ArxivRateLimitError(
            "arXiv API cooldown active after a previous HTTP 429; "
            f"wait about {wait_seconds} seconds, retry after {until.isoformat()}"
        )


def _persisted_last_request_gap(now_utc: datetime) -> Optional[float]:
    started_at = _read_request_state().get("last_request_started_at")
    if not started_at:
        return None
    try:
        last_started = datetime.fromisoformat(started_at)
        if last_started.tzinfo is None:
            last_started = last_started.replace(tzinfo=timezone.utc)
        return (now_utc - last_started.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def _build_session(*, proxies: Dict[str, str] | None = None, trust_env: bool = False) -> requests.Session:
    session = requests.Session()
    # Hidden urllib3 retries would bypass the explicit arXiv request scheduler.
    adapter = HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": REQUESTS_UA})
    session.trust_env = trust_env
    if proxies:
        session.proxies.update(proxies)
    return session


def _environment_proxies() -> Dict[str, str]:
    proxies: Dict[str, str] = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        value = os.environ.get(key)
        if value:
            proxies["https" if "https" in key.lower() else "http"] = value
    return proxies


def _build_direct_session() -> requests.Session:
    return _build_session(trust_env=False)


def _build_proxy_session() -> requests.Session:
    if PROXIES is not None:
        return _build_session(proxies=PROXIES, trust_env=False)
    env_proxies = _environment_proxies()
    if env_proxies:
        return _build_session(proxies=env_proxies, trust_env=False)
    return _build_session(trust_env=RESPECT_ENV_PROXIES)


def _host_matches_no_proxy(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(
        host == candidate.lower().lstrip(".")
        or host.endswith(f".{candidate.lower().lstrip('.')}")
        for candidate in NO_PROXY_HOSTS
    )


_ARXIV_API_HOSTS = {
    (urlparse(endpoint).hostname or "").lower()
    for endpoint in ARXIV_API_ENDPOINTS
}

def _is_arxiv_api_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() in _ARXIV_API_HOSTS and parsed.path.endswith("/api/query")


_DIRECT_SESSION = _build_direct_session()
_PROXY_SESSION = _build_proxy_session()
_HAS_PROXY_FALLBACK = PROXIES is not None or bool(_environment_proxies())


def _reserve_request_slot(_url: str) -> None:
    global _last_request_start_ts

    _check_persisted_cooldown()
    min_interval = max(0.0, RATE_LIMIT_MIN_INTERVAL_SEC)
    session_rate_limit = max(1, SESSION_RATE_LIMIT_PER_MIN)
    while True:
        sleep_for = 0.0
        with _request_slot_lock:
            now = time.monotonic()
            persisted_gap = _persisted_last_request_gap(datetime.now(timezone.utc))
            if persisted_gap is not None and persisted_gap < min_interval:
                sleep_for = max(sleep_for, min_interval - persisted_gap)
            while _request_start_window and now - _request_start_window[0] >= 60.0:
                _request_start_window.popleft()
            if len(_request_start_window) >= session_rate_limit:
                sleep_for = 60.0 - (now - _request_start_window[0])
            if _last_request_start_ts:
                sleep_for = max(sleep_for, min_interval - (now - _last_request_start_ts))
            if sleep_for <= 0.0:
                _request_start_window.append(now)
                _last_request_start_ts = now
                state = _read_request_state()
                state["last_request_started_at"] = datetime.now(timezone.utc).isoformat()
                _write_request_state(state)
                return
        time.sleep(max(sleep_for, 0.01))


def _guarded_get(session: requests.Session, url: str, *, params=None, timeout=None, stream: bool = False) -> requests.Response:
    with _request_semaphore:
        _reserve_request_slot(url)
        return session.get(
            url,
            params=params,
            timeout=timeout or REQUEST_TIMEOUT,
            stream=stream,
        )


def _should_try_proxy_fallback(exc: Exception) -> bool:
    return isinstance(exc, (RequestsConnectionError, ProxyError, SSLError))


def request_with_network_fallback(url: str, *, params=None, timeout=None, stream: bool = False) -> requests.Response:
    if ARXIV_API_USE_PROXY and _is_arxiv_api_url(url):
        if not _HAS_PROXY_FALLBACK:
            raise RuntimeError(f"arXiv API proxy mode is enabled but no proxy is configured for {url}")
        return _guarded_get(_PROXY_SESSION, url, params=params, timeout=timeout, stream=stream)
    if _host_matches_no_proxy(url):
        return _guarded_get(_DIRECT_SESSION, url, params=params, timeout=timeout, stream=stream)
    try:
        return _guarded_get(_DIRECT_SESSION, url, params=params, timeout=timeout, stream=stream)
    except Exception as exc:
        if not _HAS_PROXY_FALLBACK or not _should_try_proxy_fallback(exc):
            raise
        if DEBUG:
            print(f"[WARN] direct request failed for {url} ({exc}); retrying with proxy-aware session")
        return _guarded_get(_PROXY_SESSION, url, params=params, timeout=timeout, stream=stream)


def get_http_session() -> requests.Session:
    return _DIRECT_SESSION


def iter_pdf_urls(arxiv_id: str):
    variants = [arxiv_id]
    if "v" in arxiv_id:
        base = arxiv_id.rsplit("v", 1)[0]
        if base and base != arxiv_id:
            variants.append(base)
    seen = set()
    for endpoint in PDF_ENDPOINTS:
        for variant in variants:
            for suffix in ("", ".pdf"):
                url = f"{endpoint}/{variant}{suffix}"
                if url not in seen:
                    seen.add(url)
                    yield url


def _validate_api_payload(text: str) -> None:
    stripped = text.lstrip()
    if not stripped.startswith("<?xml") and not stripped.startswith("<feed"):
        raise ValueError("arXiv API returned non-Atom payload")


def _raise_rate_limit(endpoint: str, response: requests.Response) -> None:
    retry_after = response.headers.get("Retry-After")
    cooldown_until = _cooldown_until_from_response(response)
    state = _read_request_state()
    state["consecutive_429"] = int(state.get("consecutive_429", 0) or 0) + 1
    state["cooldown_until"] = cooldown_until.isoformat()
    state["last_429_at"] = datetime.now(timezone.utc).isoformat()
    state["last_429_endpoint"] = endpoint
    _write_request_state(state)
    body = (response.text or "").strip()
    details = []
    if retry_after:
        details.append(f"Retry-After={retry_after}")
    if body:
        details.append(f"body={body}")
    details.append(f"consecutive_429={int(state.get('consecutive_429', 0) or 0)}")
    suffix = f" ({', '.join(details)})" if details else ""
    if not retry_after:
        details.append(f"cooldown_until={cooldown_until.isoformat()}")
        suffix = f" ({', '.join(details)})" if details else ""
    raise ArxivRateLimitError(f"arXiv API is temporarily unavailable at {endpoint}: HTTP 429{suffix}")


def _get_with_fallback(params: Dict[str, Any]) -> str:
    last_exc: Exception | None = None
    for endpoint in ARXIV_API_ENDPOINTS:
        try:
            response = request_with_network_fallback(endpoint, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                _raise_rate_limit(endpoint, response)
            if response.status_code == 503:
                body = (response.text or "").strip()
                detail = f"body={body}" if body else "service unavailable"
                raise ArxivServiceUnavailableError(
                    f"arXiv API service unavailable at {endpoint}: HTTP 503 ({detail})"
                )
            response.raise_for_status()
            _validate_api_payload(response.text)
            state = _read_request_state()
            state.pop("cooldown_until", None)
            state.pop("consecutive_429", None)
            _write_request_state(state)
            return response.text
        except ArxivRateLimitError:
            raise
        except ArxivServiceUnavailableError:
            raise
        except Exception as exc:
            last_exc = exc
            if DEBUG:
                print(f"[WARN] endpoint failed: {endpoint} ({exc}); trying next...")
    if last_exc is None:
        raise RuntimeError("no arXiv API endpoints are configured")
    raise last_exc


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _entry_to_dict(entry: Any) -> Dict[str, Any]:
    categories = [
        (tag.get("term") or "").strip()
        for tag in (entry.get("tags", []) or [])
        if (tag.get("term") or "").strip()
    ]
    primary_category = (entry.get("arxiv_primary_category") or {}).get("term")
    if primary_category and primary_category not in categories:
        categories.insert(0, primary_category)
    return {
        "id": entry.get("id"),
        "title": (entry.get("title") or "").strip(),
        "summary": (entry.get("summary") or "").strip(),
        "authors": [author.get("name", "") for author in entry.get("authors", [])],
        "published": _parse_dt(entry.get("published")),
        "updated": _parse_dt(entry.get("updated")),
        "primary_category": primary_category,
        "categories": categories,
        "comment": entry.get("arxiv_comment") or "",
        "journal_ref": entry.get("arxiv_journal_ref") or "",
        "links": entry.get("links", []),
    }


def _format_arxiv_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M")


def query_cs_sorted(start: int, max_results: int):
    xml = _get_with_fallback({
        "search_query": "cat:cs.*",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": start,
        "max_results": max_results,
    })
    return feedparser.parse(xml)


def query_cs_window(start_utc: datetime, end_utc: datetime, start: int, max_results: int):
    return query_category_window("cs.*", start_utc, end_utc, start, max_results)


def query_category_window(category: str, start_utc: datetime, end_utc: datetime, start: int, max_results: int):
    xml = _get_with_fallback({
        "search_query": (
            f"submittedDate:[{_format_arxiv_datetime(start_utc)} TO "
            f"{_format_arxiv_datetime(end_utc)}] AND cat:{category}"
        ),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": start,
        "max_results": max_results,
    })
    return feedparser.parse(xml)


def _candidate_page_sizes(initial_page_size: int) -> list[int]:
    candidates = [initial_page_size, 1000, 500, 200]
    ordered: list[int] = []
    for candidate in candidates:
        normalized = max(1, min(initial_page_size, candidate))
        if normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _feed_reported_items_per_page(feed: Any) -> int | None:
    metadata = getattr(feed, "feed", None)
    if isinstance(metadata, dict):
        candidates = [metadata.get("opensearch_itemsperpage")]
    else:
        candidates = [getattr(metadata, "opensearch_itemsperpage", None)]
    for value in candidates:
        try:
            parsed = int(value)
            if parsed > 0:
                return parsed
        except Exception:
            continue
    return None


def _query_cs_window_adaptive(
    start_utc: datetime,
    end_utc: datetime,
    start: int,
    preferred_page_size: int,
    on_request_progress=None,
):
    last_error: ArxivServiceUnavailableError | None = None
    for page_size in _candidate_page_sizes(preferred_page_size):
        try:
            feed = query_cs_window(start_utc, end_utc, start, page_size)
            return feed, _feed_reported_items_per_page(feed)
        except ArxivServiceUnavailableError as exc:
            last_error = exc
            message = f"arXiv API 503 at start={start}, max_results={page_size}; reducing page size"
            if DEBUG:
                print(f"[WARN] {message}")
            if on_request_progress:
                on_request_progress(message)
            continue
    raise last_error or ArxivServiceUnavailableError("arXiv API service unavailable")


def _query_category_window_adaptive(
    category: str,
    start_utc: datetime,
    end_utc: datetime,
    start: int,
    preferred_page_size: int,
    on_request_progress=None,
):
    last_error: ArxivServiceUnavailableError | None = None
    for page_size in _candidate_page_sizes(preferred_page_size):
        try:
            feed = query_category_window(category, start_utc, end_utc, start, page_size)
            return feed, _feed_reported_items_per_page(feed)
        except ArxivServiceUnavailableError as exc:
            last_error = exc
            message = f"arXiv API 503 at category={category}, start={start}, max_results={page_size}; reducing page size"
            if DEBUG:
                print(f"[WARN] {message}")
            if on_request_progress:
                on_request_progress(message)
            continue
    raise last_error or ArxivServiceUnavailableError("arXiv API service unavailable")


def iter_recent_cs_by_category(
    start_utc,
    end_utc,
    start_offset: int = 0,
    on_page_complete=None,
    on_request_progress=None,
) -> Iterable[Dict[str, Any]]:
    page_size = max(1, MAX_RESULTS_PER_PAGE)
    categories = list(ARXIV_PRIMARY_CATEGORY_PREFIXES)
    seen_ids: set[str] = set()
    for category_index, category in enumerate(categories):
        start = max(0, start_offset) if category_index == 0 else 0
        previous_page_ids: list[str] | None = None
        if on_request_progress:
            on_request_progress(f"querying arXiv category {category_index + 1}/{len(categories)}: {category}")
        while True:
            current_start = start
            feed, actual_page_size = _query_category_window_adaptive(
                category,
                start_utc,
                end_utc,
                start,
                page_size,
                on_request_progress=on_request_progress,
            )
            entries = feed.entries or []
            if not entries:
                break
            page_ids: list[str] = []
            rows: list[Dict[str, Any]] = []
            for entry in entries:
                row = _entry_to_dict(entry)
                arxiv_id = get_arxiv_id(row)
                page_ids.append(arxiv_id)
                rows.append(row)
            if page_ids and page_ids == previous_page_ids:
                break
            previous_page_ids = page_ids
            for row in rows:
                arxiv_id = get_arxiv_id(row)
                if arxiv_id in seen_ids:
                    continue
                seen_ids.add(arxiv_id)
                yield row
            next_start = current_start + len(entries)
            if on_page_complete:
                on_page_complete(
                    current_start=current_start,
                    next_start=next_start,
                    fetched_count=len(entries),
                )
            if actual_page_size is not None and len(entries) < actual_page_size:
                break
            start = next_start


def iter_recent_cs_single(
    start_utc=None,
    end_utc=None,
    start_offset: int = 0,
    on_page_complete=None,
    on_request_progress=None,
) -> Iterable[Dict[str, Any]]:
    start = max(0, start_offset)
    page_size = max(1, MAX_RESULTS_PER_PAGE)
    previous_page_ids: list[str] | None = None
    while True:
        current_start = start
        if start_utc and end_utc:
            feed, actual_page_size = _query_cs_window_adaptive(
                start_utc,
                end_utc,
                start,
                page_size,
                on_request_progress=on_request_progress,
            )
        else:
            feed = query_cs_sorted(start, page_size)
            actual_page_size = page_size
        entries = feed.entries or []
        if not entries:
            break
        page_ids: list[str] = []
        rows: list[Dict[str, Any]] = []
        for entry in entries:
            row = _entry_to_dict(entry)
            page_ids.append(get_arxiv_id(row))
            rows.append(row)
        if page_ids and page_ids == previous_page_ids:
            break
        previous_page_ids = page_ids
        for row in rows:
            published = row["published"]
            if start_utc and published and published < start_utc:
                return
            yield row
        next_start = current_start + len(entries)
        if on_page_complete:
            on_page_complete(
                current_start=current_start,
                next_start=next_start,
                fetched_count=len(entries),
            )
        if actual_page_size is not None and len(entries) < actual_page_size:
            break
        start = next_start


def iter_recent_cs(
    start_utc=None,
    end_utc=None,
    start_offset: int = 0,
    on_page_complete=None,
    on_request_progress=None,
    **_ignored,
) -> Iterable[Dict[str, Any]]:
    if start_utc and end_utc:
        return iter_recent_cs_by_category(
            start_utc=start_utc,
            end_utc=end_utc,
            start_offset=start_offset,
            on_page_complete=on_page_complete,
            on_request_progress=on_request_progress,
        )
    return iter_recent_cs_single(
        start_utc=start_utc,
        end_utc=end_utc,
        start_offset=start_offset,
        on_page_complete=on_page_complete,
        on_request_progress=on_request_progress,
    )


def extract_pdf_url(entry: Dict[str, Any]) -> str | None:
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf" or link.get("title") == "pdf":
            return link.get("href")
    return None


def get_arxiv_id(entry: Dict[str, Any]) -> str:
    raw = (entry.get("id") or "").rstrip("/")
    return raw.split("/")[-1]
