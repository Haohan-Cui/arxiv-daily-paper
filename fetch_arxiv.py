from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import feedparser
import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ProxyError, RequestException, SSLError
from urllib3.util.retry import Retry

from config import (
    ARXIV_API_ENDPOINTS,
    FAILOVER_ON_429,
    MAX_PAGES,
    MAX_RESULTS_PER_PAGE,
    PROXIES,
    RATE_LIMIT_MIN_INTERVAL_SEC,
    REQUESTS_UA,
    REQUEST_TIMEOUT,
    RESPECT_ENV_PROXIES,
    RETRY_BACKOFF,
    RETRY_TOTAL,
)
from config import DEBUG

try:
    from config import USE_SHARDED_BASELINE
except Exception:
    USE_SHARDED_BASELINE = True

CS_SHARDS = [
    "cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.RO", "cs.CR", "cs.DS",
    "cs.IR", "cs.MA", "cs.SE", "cs.NI", "cs.DC", "cs.SD", "cs.HC",
    "cs.MM", "cs.SY", "cs.LO", "cs.LI",
]

PDF_ENDPOINTS = [
    "https://arxiv.org/pdf",
    "https://export.arxiv.org/pdf",
    "http://export.arxiv.org/pdf",
]

_last_call_ts_per_host: Dict[str, float] = {}


def _build_retry_adapter() -> HTTPAdapter:
    retry = Retry(
        total=RETRY_TOTAL,
        connect=RETRY_TOTAL,
        read=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    return HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)


def _environment_proxies() -> Dict[str, str]:
    proxies: Dict[str, str] = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        value = os.environ.get(key)
        if not value:
            continue
        scheme = "https" if "https" in key.lower() else "http"
        proxies[scheme] = value
    return proxies


def _build_session(*, force_env_proxies: bool = False) -> requests.Session:
    session = requests.Session()
    adapter = _build_retry_adapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": REQUESTS_UA})

    if PROXIES is not None:
        session.trust_env = False
        session.proxies.update(PROXIES)
    elif force_env_proxies:
        env_proxies = _environment_proxies()
        if env_proxies:
            session.trust_env = False
            session.proxies.update(env_proxies)
        else:
            session.trust_env = RESPECT_ENV_PROXIES
    else:
        session.trust_env = RESPECT_ENV_PROXIES

    return session


_DIRECT_SESSION = _build_session()
_PROXY_SESSION = _build_session(force_env_proxies=True)
_HAS_PROXY_FALLBACK = PROXIES is not None or bool(_environment_proxies())


def _rate_limit_wait(url: str):
    host = urlparse(url).hostname or ""
    now = time.monotonic()
    last = _last_call_ts_per_host.get(host, 0.0)
    gap = now - last
    if gap < RATE_LIMIT_MIN_INTERVAL_SEC:
        time.sleep(RATE_LIMIT_MIN_INTERVAL_SEC - gap)
    _last_call_ts_per_host[host] = time.monotonic()


def _should_try_proxy_fallback(exc: Exception) -> bool:
    return isinstance(exc, (RequestsConnectionError, ProxyError, SSLError))


def request_with_network_fallback(url: str, *, params=None, timeout=None) -> requests.Response:
    _rate_limit_wait(url)
    try:
        return _DIRECT_SESSION.get(url, params=params, timeout=timeout or REQUEST_TIMEOUT)
    except Exception as exc:
        if not _HAS_PROXY_FALLBACK or not _should_try_proxy_fallback(exc):
            raise
        if DEBUG:
            print(f"[WARN] direct request failed for {url} ({exc}); retrying with proxy-aware session")
        _rate_limit_wait(url)
        return _PROXY_SESSION.get(url, params=params, timeout=timeout or REQUEST_TIMEOUT)


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
            url = f"{endpoint}/{variant}.pdf"
            if url in seen:
                continue
            seen.add(url)
            yield url


def _validate_api_payload(text: str) -> None:
    stripped = text.lstrip()
    if not stripped.startswith("<?xml") and not stripped.startswith("<feed"):
        raise ValueError("arXiv API returned non-Atom payload")


def _get_with_fallback(params: Dict[str, Any]) -> str:
    last_exc = None
    for i, endpoint in enumerate(ARXIV_API_ENDPOINTS):
        try:
            response = request_with_network_fallback(endpoint, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                try:
                    sleep_sec = int(retry_after) if retry_after is not None else 5
                except Exception:
                    sleep_sec = 5
                if DEBUG:
                    print(f"[WARN] 429 from {endpoint}, Retry-After={sleep_sec}s; params={params}")
                time.sleep(sleep_sec)
                if FAILOVER_ON_429 and i + 1 < len(ARXIV_API_ENDPOINTS):
                    continue
                response = request_with_network_fallback(endpoint, params=params, timeout=REQUEST_TIMEOUT)

            response.raise_for_status()
            _validate_api_payload(response.text)
            return response.text
        except Exception as exc:
            last_exc = exc
            if DEBUG:
                print(f"[WARN] endpoint failed: {endpoint} ({exc}); trying next...")
            time.sleep(1.0)
            continue

    raise last_exc


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _entry_to_dict(entry: Any) -> Dict[str, Any]:
    return {
        "id": entry.get("id"),
        "title": (entry.get("title") or "").strip(),
        "summary": (entry.get("summary") or "").strip(),
        "authors": [author.get("name", "") for author in entry.get("authors", [])],
        "published": _parse_dt(entry.get("published")),
        "updated": _parse_dt(entry.get("updated")),
        "primary_category": (entry.get("arxiv_primary_category") or {}).get("term"),
        "comment": entry.get("arxiv_comment") or "",
        "journal_ref": entry.get("arxiv_journal_ref") or "",
        "links": entry.get("links", []),
    }


def query_cs_sorted(start: int, max_results: int):
    params = {
        "search_query": "cat:cs.*",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": start,
        "max_results": max_results,
    }
    xml = _get_with_fallback(params)
    return feedparser.parse(xml)


def _query_feed(search_query: str, sort_by: str, start: int, max_results: int):
    params = {
        "search_query": search_query,
        "sortBy": sort_by,
        "sortOrder": "descending",
        "start": start,
        "max_results": max_results,
    }
    xml = _get_with_fallback(params)
    return feedparser.parse(xml)


def _query_cat_submitted(cat: str, start: int, max_results: int):
    return _query_feed(f"cat:{cat}", "submittedDate", start, max_results)


def _query_any(query: str, start: int, max_results: int):
    return _query_feed(query, "submittedDate", start, max_results)


def iter_recent_cs_single(start_utc=None) -> Iterable[Dict[str, Any]]:
    start = 0
    page_size = MAX_RESULTS_PER_PAGE
    for page in range(MAX_PAGES):
        feed = query_cs_sorted(start, page_size)
        entries = feed.entries or []
        if not entries:
            if DEBUG:
                print(f"[DEBUG] single page={page} start={start} -> 0 entries, stop.")
            break

        for entry in entries:
            row = _entry_to_dict(entry)
            pub = row["published"]
            if start_utc and pub and pub < start_utc:
                if DEBUG:
                    print(f"[DEBUG] stop at pub={pub}, before window start={start_utc}")
                return
            yield row
        start += page_size


def iter_recent_cs_sharded(start_utc=None) -> Iterable[Dict[str, Any]]:
    page_size = min(MAX_RESULTS_PER_PAGE, 200)
    for shard in CS_SHARDS:
        start = 0
        stop_shard = False
        for page in range(MAX_PAGES):
            if stop_shard:
                break
            feed = _query_cat_submitted(shard, start, page_size)
            entries = feed.entries or []
            if not entries:
                if DEBUG:
                    print(f"[DEBUG] shard page={page} start={start} shard={shard} -> 0 entries, stop shard.")
                break
            for entry in entries:
                row = _entry_to_dict(entry)
                pub = row["published"]
                if start_utc and pub and pub < start_utc:
                    if DEBUG:
                        print(f"[DEBUG] stop shard={shard} at pub={pub}, before window start={start_utc}")
                    stop_shard = True
                    break
                yield row
            start += page_size


def iter_recent_cs(limit_pages: int = MAX_PAGES, page_size: int = MAX_RESULTS_PER_PAGE, start_utc=None) -> Iterable[Dict[str, Any]]:
    if USE_SHARDED_BASELINE:
        return iter_recent_cs_sharded(start_utc=start_utc)
    return iter_recent_cs_single(start_utc=start_utc)


def search_by_terms(terms, limit_pages=5, page_size=200, start_utc=None):
    if not terms:
        return
    or_block = " OR ".join([f'all:{term}' for term in terms])
    query = f"(cat:cs.*) AND ({or_block})"
    start = 0
    for page in range(limit_pages):
        feed = _query_any(query, start, page_size)
        entries = feed.entries or []
        if not entries:
            if DEBUG:
                print(f"[DEBUG] per-org page={page} start={start} -> 0 entries, stop.")
            break

        stop_search = False
        for entry in entries:
            row = _entry_to_dict(entry)
            pub = row["published"]
            if start_utc and pub and pub < start_utc:
                stop_search = True
                break
            yield row
        if stop_search:
            if DEBUG:
                print(f"[DEBUG] per-org stop at page={page} start={start}, older than window start={start_utc}")
            break
        start += page_size


def extract_pdf_url(entry: Dict[str, Any]) -> str | None:
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            return link.get("href")
    return None


def get_arxiv_id(entry: Dict[str, Any]) -> str:
    raw = (entry.get("id") or "").rstrip("/")
    return raw.split("/")[-1]
