# prefetch.py
from __future__ import annotations
import os, re, requests
from typing import Dict, Any, List
from pathlib import Path
from requests.exceptions import HTTPError
from config import PDF_CACHE_DIR, CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC
from fetch_arxiv import get_arxiv_id  # 你之前已添加的工具函数

SAFE_NAME = re.compile(r"[^a-zA-Z0-9._/-]+")

def ensure_dir(p: str | Path):
    Path(p).mkdir(parents=True, exist_ok=True)

def canonical_pdf_urls(arxiv_id: str) -> List[str]:
    urls = [f"https://arxiv.org/pdf/{arxiv_id}.pdf"]
    if "v" in arxiv_id:
        base = arxiv_id.split("v")[0]
        if base and base != arxiv_id:
            urls.append(f"https://arxiv.org/pdf/{base}.pdf")
    return urls

def cache_pdfs(entries: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    预下载所有候选 entry 到 PDF_CACHE_DIR，返回 {arxiv_id: local_path}
    已存在则跳过。
    """
    ensure_dir(PDF_CACHE_DIR)
    out: Dict[str, str] = {}
    sess = requests.Session()
    sess.headers.update({"User-Agent": "DailyPaper/1.0 (+cache)"})

    for e in entries:
        aid = get_arxiv_id(e)  # e.g. 2506.16012v2
        rel = SAFE_NAME.sub("_", aid) + ".pdf"
        fpath = Path(PDF_CACHE_DIR) / rel
        if fpath.exists():
            out[aid] = str(fpath)
            continue
        last_err = None
        for url in canonical_pdf_urls(aid):
            try:
                r = sess.get(url, timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC))
                r.raise_for_status()
                with open(fpath, "wb") as f:
                    f.write(r.content)
                out[aid] = str(fpath)
                break
            except HTTPError as e2:
                last_err = e2
                if e2.response is not None and e2.response.status_code == 404:
                    continue
                else:
                    break
            except Exception as e3:
                last_err = e3
                break
        if aid not in out:
            print(f"[WARN] 缓存失败 {aid}: {last_err}")
    return out
