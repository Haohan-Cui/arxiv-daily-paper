# fetch_arxiv.py
from __future__ import annotations
import time, requests, feedparser, os
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, List, Optional
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from config import (
    ARXIV_API_ENDPOINTS, REQUEST_TIMEOUT, RETRY_TOTAL, RETRY_BACKOFF,
    REQUESTS_UA, PROXIES, RESPECT_ENV_PROXIES,
    MAX_RESULTS_PER_PAGE, MAX_PAGES,
)
from config import DEBUG

# 分片控制：可在 config.py 里覆盖
try:
    from config import USE_SHARDED_BASELINE
except Exception:
    USE_SHARDED_BASELINE = True

# 常见计算机科学子类分片
CS_SHARDS = [
    "cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.RO", "cs.CR", "cs.DS",
    "cs.IR", "cs.MA", "cs.SE", "cs.NI", "cs.DC", "cs.SD", "cs.HC",
    "cs.MM", "cs.IT", "cs.CY", "cs.SY", "cs.LO", "cs.LI", "cs.SI",
]

# ---- HTTP session ----
def _build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=RETRY_TOTAL,
        connect=RETRY_TOTAL,
        read=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)

    s.headers.update({"User-Agent": REQUESTS_UA})

    if PROXIES is not None:
        s.proxies.update(PROXIES)
    else:
        if not RESPECT_ENV_PROXIES:
            for k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                os.environ.pop(k, None)
    return s

_SESSION = _build_session()

# ---- API Core ----
def _get_with_fallback(params: Dict[str, Any]) -> str:
    last_exc = None
    for endpoint in ARXIV_API_ENDPOINTS:
        try:
            r = _SESSION.get(endpoint, params=params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last_exc = e
            time.sleep(0.5)
    raise last_exc

# ---- Utilities ----
def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def _entry_to_dict(e: Any) -> Dict[str, Any]:
    return {
        "id": e.get("id"),
        "title": (e.get("title") or "").strip(),
        "summary": (e.get("summary") or "").strip(),
        "authors": [a.get("name", "") for a in e.get("authors", [])],
        "published": _parse_dt(e.get("published")),
        "updated": _parse_dt(e.get("updated")),
        "primary_category": (e.get("arxiv_primary_category") or {}).get("term"),
        "comment": e.get("arxiv_comment") or "",
        "journal_ref": e.get("arxiv_journal_ref") or "",
        "links": e.get("links", []),
    }

# ---- Query Helpers ----
def query_cs_sorted(start: int, max_results: int):
    """主查询入口：按时间降序获取 cs.*"""
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

# ---- Baseline Iterators ----
def iter_recent_cs_single(start_utc=None) -> Iterable[Dict[str, Any]]:
    """单一大类抓取：适用于非分片模式"""
    start = 0
    page_size = MAX_RESULTS_PER_PAGE
    for page in range(MAX_PAGES):
        feed = query_cs_sorted(start, page_size)
        entries = feed.entries or []
        if not entries:
            if DEBUG:
                print(f"[DEBUG] single page={page} start={start} -> 0 entries, stop.")
            break

        for e in entries:
            row = _entry_to_dict(e)
            pub = row["published"]
            if start_utc and pub and pub < start_utc:
                if DEBUG:
                    print(f"[DEBUG] stop at pub={pub}, before window start={start_utc}")
                return
            yield row
        start += page_size

def iter_recent_cs_sharded(start_utc=None) -> Iterable[Dict[str, Any]]:
    """分片抓取：遍历多个 cs 子类"""
    page_size = min(MAX_RESULTS_PER_PAGE, 200)
    for shard in CS_SHARDS:
        start = 0
        stop_shard = False  # ✅ 控制是否提前停止整个 shard
        for page in range(MAX_PAGES):
            if stop_shard:
                break
            feed = _query_cat_submitted(shard, start, page_size)
            entries = feed.entries or []
            if not entries:
                if DEBUG:
                    print(f"[DEBUG] shard page={page} start={start} shard={shard} -> 0 entries, stop shard.")
                break
            for e in entries:
                row = _entry_to_dict(e)
                pub = row["published"]
                if start_utc and pub and pub < start_utc:
                    if DEBUG:
                        print(f"[DEBUG] stop shard={shard} at pub={pub}, before window start={start_utc}")
                    stop_shard = True   # ✅ 标记整个 shard 需要停止
                    break               # 跳出当前 entries 循环
                yield row
            start += page_size

# ---- Unified public interface ----
def iter_recent_cs(limit_pages: int = MAX_PAGES, page_size: int = MAX_RESULTS_PER_PAGE, start_utc=None) -> Iterable[Dict[str, Any]]:
    """供 app.py 调用的统一入口"""
    if USE_SHARDED_BASELINE:
        return iter_recent_cs_sharded(start_utc=start_utc)
    else:
        return iter_recent_cs_single(start_utc=start_utc)

# ---- Per-org search ----
def search_by_terms(terms, limit_pages=5, page_size=200):
    """机构名关键字搜索 (cat:cs.*) AND (all:term1 OR all:term2 ...)"""
    if not terms:
        return
    or_block = " OR ".join([f'all:{t}' for t in terms])
    query = f"(cat:cs.*) AND ({or_block})"
    start = 0
    for page in range(limit_pages):
        feed = _query_any(query, start, page_size)
        entries = feed.entries or []
        if not entries:
            if DEBUG:
                print(f"[DEBUG] per-org page={page} start={start} -> 0 entries, stop.")
            break
        for e in entries:
            yield _entry_to_dict(e)
        start += page_size

# ---- Misc helpers ----
def extract_pdf_url(entry: Dict[str, Any]) -> str | None:
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            return link.get("href")
    return None

def get_arxiv_id(entry: Dict[str, Any]) -> str:
    raw = (entry.get("id") or "").rstrip("/")
    return raw.split("/")[-1]
