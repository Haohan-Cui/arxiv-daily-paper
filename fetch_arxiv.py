# fetch_arxiv.py
from __future__ import annotations
import time, requests, feedparser, os
from datetime import datetime, timezone
from typing import Dict, Any, Iterable, List
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from config import (
    ARXIV_API_ENDPOINTS, REQUEST_TIMEOUT, RETRY_TOTAL, RETRY_BACKOFF,
    REQUESTS_UA, PROXIES, RESPECT_ENV_PROXIES, MAX_RESULTS_PER_PAGE, MAX_PAGES
)

def _build_session() -> requests.Session:
    s = requests.Session()
    # 挂载带重试的适配器
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

    # User-Agent
    s.headers.update({"User-Agent": REQUESTS_UA})

    # 代理：优先使用显式 PROXIES，否则尊重环境变量（可通过 NO_PROXY 绕过域名）
    if PROXIES is not None:
        s.proxies.update(PROXIES)
    else:
        if not RESPECT_ENV_PROXIES:
            # 清空环境代理
            for k in ["HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"]:
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
            # 小憩退避后继续尝试下一个端点
            time.sleep(0.5)
    # 所有端点都失败，抛最后一个异常
    raise last_exc

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

def _query_any(query: str, start: int, max_results: int):
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": start,
        "max_results": max_results,
    }
    xml = _get_with_fallback(params)
    return feedparser.parse(xml)

def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def iter_recent_cs(limit_pages: int = MAX_PAGES, page_size: int = MAX_RESULTS_PER_PAGE) -> Iterable[Dict[str, Any]]:
    start = 0
    for _ in range(limit_pages):
        feed = query_cs_sorted(start, page_size)
        if not feed.entries:
            break
        for e in feed.entries:
            yield {
                "id": e.get("id"),
                "title": (e.get("title") or "").strip(),
                "summary": (e.get("summary") or "").strip(),
                "authors": [a.get("name","") for a in e.get("authors", [])],
                "published": _parse_dt(e.get("published")),
                "updated": _parse_dt(e.get("updated")),
                "primary_category": (e.get("arxiv_primary_category") or {}).get("term"),
                "comment": e.get("arxiv_comment") or "",
                "journal_ref": e.get("arxiv_journal_ref") or "",
                "links": e.get("links", []),
            }
        start += page_size

def extract_pdf_url(entry: Dict[str, Any]) -> str | None:
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            return link.get("href")
    return None
# fetch_arxiv.py（追加在文件末尾）

def search_by_terms(terms, limit_pages=5, page_size=200):
    """
    terms: ['"Google"', '"Google Research"'] -> 构造 (cat:cs.*) AND (all:term1 OR all:term2 ...)
    返回与 iter_recent_cs 相同结构的 entries 迭代器
    """
    if not terms:
        return
    # all:term 做 OR
    or_block = " OR ".join([f'all:{t}' for t in terms])
    query = f"(cat:cs.*) AND ({or_block})"
    start = 0
    for _ in range(limit_pages):
        feed = _query_any(query, start, page_size)
        if not feed.entries:
            break
        for e in feed.entries:
            yield {
                "id": e.get("id"),
                "title": (e.get("title") or "").strip(),
                "summary": (e.get("summary") or "").strip(),
                "authors": [a.get("name","") for a in e.get("authors", [])],
                "published": _parse_dt(e.get("published")),
                "updated": _parse_dt(e.get("updated")),
                "primary_category": (e.get("arxiv_primary_category") or {}).get("term"),
                "comment": e.get("arxiv_comment") or "",
                "journal_ref": e.get("arxiv_journal_ref") or "",
                "links": e.get("links", []),
            }
        start += page_size
def get_arxiv_id(entry: Dict[str, Any]) -> str:
    """
    从 entry['id']（形如 https://arxiv.org/abs/2506.16012v2）提取 arXiv ID：2506.16012v2
    旧式条目可能是 http://arxiv.org/abs/cs/0301011v1 -> 返回 cs/0301011v1
    """
    raw = (entry.get("id") or "").rstrip("/")
    last = raw.split("/")[-1]
    return last  # 例如 2506.16012v2 或 cs/0301011v1