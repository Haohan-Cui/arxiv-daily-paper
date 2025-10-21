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

# 可在 config.py 里加开关；这里给默认值，若你已在 config 里声明同名变量则忽略
try:
    from config import USE_SHARDED_BASELINE
except Exception:
    USE_SHARDED_BASELINE = True

# 常见 CS 子类分片（可按需增减）
CS_SHARDS = [
    "cs.AI", "cs.CL", "cs.CV", "cs.LG", "cs.RO", "cs.CR", "cs.DS",
    "cs.IR", "cs.MA", "cs.SE", "cs.NI", "cs.DC", "cs.SD", "cs.HC",
    "cs.MM", "cs.IT", "cs.CY", "cs.SY", "cs.LO", "cs.LI", "cs.SI",
]

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

def _debug_page_hint(kind: str, page: int, start: int, entries: List[Dict[str, Any]], shard: Optional[str]=None):
    if not DEBUG or not entries:
        return
    first = entries[0]; last = entries[-1]
    f_pub = first.get("published"); f_upd = first.get("updated")
    l_pub = last.get("published");  l_upd = last.get("updated")
    shard_info = f" shard={shard}" if shard else ""
    print(
        "[DEBUG] {kind} page={page} start={start}{shard} count={cnt} "
        "first(pub={fp}, upd={fu}) last(pub={lp}, upd={lu})"
        .format(
            kind=kind, page=page, start=start, shard=shard_info, cnt=len(entries),
            fp=f_pub.isoformat() if f_pub else None,
            fu=f_upd.isoformat() if f_upd else None,
            lp=l_pub.isoformat() if l_pub else None,
            lu=l_upd.isoformat() if l_upd else None,
        )
    )

# ---- API helpers
def _query_feed(search_query: str, sort_by: str, start: int, max_results: int):
    params = {
        "search_query": search_query,
        "sortBy": sort_by,              # 'submittedDate' or 'lastUpdatedDate'
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

# ---- Baseline: single broad query (may be rate-limited on some mirrors)
def iter_recent_cs_single() -> Iterable[Dict[str, Any]]:
    start = 0
    page_size = MAX_RESULTS_PER_PAGE
    for page in range(MAX_PAGES):
        feed = _query_feed("cat:cs.*", "submittedDate", start, page_size)
        entries = feed.entries or []
        if not entries:
            if DEBUG:
                print(f"[DEBUG] single page={page} start={start} -> 0 entries, stop.")
            break
        rows = [_entry_to_dict(e) for e in entries]
        _debug_page_hint("single", page, start, rows)
        for row in rows:
            yield row
        start += page_size

# ---- Baseline (recommended): shard by category (cs.AI, cs.CL, ...)
def iter_recent_cs_sharded() -> Iterable[Dict[str, Any]]:
    """
    对 cs.* 做分片抓取，绕开大类限流/忽略分页的问题。
    每个 shard 都按照 submittedDate desc 做分页，最多 MAX_PAGES 页（总量=shards*MAX_PAGES*page_size）。
    """
    page_size = min(MAX_RESULTS_PER_PAGE, 200)  # 保守取 ≤200
    for shard in CS_SHARDS:
        start = 0
        for page in range(MAX_PAGES):
            feed = _query_cat_submitted(shard, start, page_size)
            entries = feed.entries or []
            if not entries:
                if DEBUG:
                    print(f"[DEBUG] shard page={page} start={start} shard={shard} -> 0 entries, stop shard.")
                break
            rows = [_entry_to_dict(e) for e in entries]
            _debug_page_hint("shard", page, start, rows, shard=shard)
            for row in rows:
                yield row
            start += page_size

# ---- Public iterator used by app.py
def iter_recent_cs() -> Iterable[Dict[str, Any]]:
    """
    默认优先“分片抓取”。如需退回单一 'cat:cs.*' 查询，可在 config.py 设置：
        USE_SHARDED_BASELINE = False
    """
    if USE_SHARDED_BASELINE:
        yield from iter_recent_cs_sharded()
    else:
        yield from iter_recent_cs_single()

def search_by_terms(terms, limit_pages=5, page_size=200):
    """
    (cat:cs.*) AND (all:term1 OR all:term2 ...)
    """
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
        rows = [_entry_to_dict(e) for e in entries]
        for row in rows:
            yield row
        start += page_size

def extract_pdf_url(entry: Dict[str, Any]) -> str | None:
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            return link.get("href")
    return None

def get_arxiv_id(entry: Dict[str, Any]) -> str:
    raw = (entry.get("id") or "").rstrip("/")
    last = raw.split("/")[-1]
    return last
