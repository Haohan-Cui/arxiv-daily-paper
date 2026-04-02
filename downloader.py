from __future__ import annotations
import re, concurrent.futures
from typing import List, Dict, Any
from pathlib import Path
from requests.exceptions import HTTPError
from config import DOWNLOAD_CONCURRENCY, CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC, LIMIT_PER_ORG
from fetch_arxiv import get_arxiv_id, get_http_session, iter_pdf_urls

SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_filename(s: str) -> str:
    s = s.strip().replace(" ", "_")
    return SAFE_NAME.sub("_", s)[:160]

def ensure_dir(p: str | Path):
    Path(p).mkdir(parents=True, exist_ok=True)

session = get_http_session()

def _download_one(entry: Dict[str, Any], out_dir: Path) -> str | None:
    arxiv_id = get_arxiv_id(entry)
    fname = safe_filename(f"{arxiv_id}.pdf")
    fpath = out_dir / fname
    if fpath.exists():
        return str(fpath)

    last_error = None
    for url in iter_pdf_urls(arxiv_id):
        try:
            r = session.get(url, timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC))
            r.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(r.content)
            return str(fpath)
        except HTTPError as e:
            last_error = e
            if e.response is not None and e.response.status_code == 404:
                continue
            continue
        except Exception as e:
            last_error = e
            continue

    print(f"[WARN] 下载失败 {arxiv_id}: {last_error}")
    return None

def download_pdfs_for_org(org: str, entries: List[Dict[str, Any]], out_dir: Path, dry_run: bool) -> List[str]:
    ensure_dir(out_dir)
    files: List[str] = []
    work_entries = entries[:LIMIT_PER_ORG] if (LIMIT_PER_ORG and LIMIT_PER_ORG > 0) else entries

    if dry_run:
        for e in work_entries:
            print(f"[DRY-RUN] {org}: would download {e.get('id')} -> {out_dir}")
        return files

    with concurrent.futures.ThreadPoolExecutor(max_workers=DOWNLOAD_CONCURRENCY) as ex:
        futs = [ex.submit(_download_one, e, out_dir) for e in work_entries]
        for fu in concurrent.futures.as_completed(futs):
            path = fu.result()
            if path:
                files.append(path)
    return files
