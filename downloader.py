from __future__ import annotations
import os, re, concurrent.futures, requests
from typing import List, Dict, Any
from pathlib import Path
from config import DOWNLOAD_CONCURRENCY, CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC, LIMIT_PER_ORG
from fetch_arxiv import get_arxiv_id  # <<< 新增引用
from requests.exceptions import HTTPError

SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")

def safe_filename(s: str) -> str:
    s = s.strip().replace(" ", "_")
    return SAFE_NAME.sub("_", s)[:160]

def ensure_dir(p: str | Path):
    Path(p).mkdir(parents=True, exist_ok=True)

# 可选：用与 fetch 相同的带重试 Session（若你已在 fetch_arxiv 里封装了 _SESSION，可复用）
import requests
_session = requests.Session()
_session.headers.update({"User-Agent": "DailyPaper/1.0 (+contact: your_email@example.com)"})

def _canonical_pdf_urls(arxiv_id: str):
    """
    返回一个候选 URL 列表：
      1) https://arxiv.org/pdf/<id>.pdf
      2) 如果 id 带版本号（如 v2），再尝试去版本：https://arxiv.org/pdf/<base>.pdf
    """
    urls = [f"https://arxiv.org/pdf/{arxiv_id}.pdf"]
    if "v" in arxiv_id:
        base = arxiv_id.split("v")[0]
        if base and base != arxiv_id:
            urls.append(f"https://arxiv.org/pdf/{base}.pdf")
    return urls

def _download_one(entry: Dict[str, Any], out_dir: Path) -> str | None:
    arxiv_id = get_arxiv_id(entry)  # 例如 2506.16012v2
    fname = safe_filename(f"{arxiv_id}.pdf")
    fpath = out_dir / fname
    if fpath.exists():
        return str(fpath)

    last_error = None
    for url in _canonical_pdf_urls(arxiv_id):
        try:
            r = _session.get(url, timeout=(CONNECT_TIMEOUT_SEC, READ_TIMEOUT_SEC))
            r.raise_for_status()
            with open(fpath, "wb") as f:
                f.write(r.content)
            return str(fpath)
        except HTTPError as e:
            # 404 再试下一个候选；其他错误直接记录
            last_error = e
            if e.response is not None and e.response.status_code == 404:
                continue
            else:
                break
        except Exception as e:
            last_error = e
            break

    # 走到这里说明所有候选都失败了：记录并跳过（不要抛到线程外导致整体中断）
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

