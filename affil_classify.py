# affil_classify.py
from __future__ import annotations
from typing import Dict, Any, List, DefaultDict
from collections import defaultdict
import re, os, shutil
from config import INSTITUTIONS_PATTERNS, MAX_PDF_PAGES_TO_SCAN, USE_HARDLINKS
from pdf_affil import extract_affiliation_text

def compile_patterns():
    return {org: [re.compile(p, re.IGNORECASE) for p in pats]
            for org, pats in INSTITUTIONS_PATTERNS.items()}

def classify_from_pdf(entries: List[Dict[str, Any]], id2pdf: Dict[str, str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    用 PDF 作者/单位区文本做匹配。返回 {org: [entries...]}
    """
    cpats = compile_patterns()
    buckets: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)

    for e in entries:
        aid = (e.get("id") or "").split("/")[-1]  # 与 get_arxiv_id 一致即可
        pdf_path = id2pdf.get(aid)
        if not pdf_path or not os.path.exists(pdf_path):
            continue
        text = extract_affiliation_text(pdf_path, max_pages=MAX_PDF_PAGES_TO_SCAN)
        if not text:
            continue
        for org, pats in cpats.items():
            if any(p.search(text) for p in pats):
                buckets[org].append(e)
    return buckets

def place_pdf_into_org_dir(aid: str, src_pdf: str, org_dir: str) -> str | None:
    os.makedirs(org_dir, exist_ok=True)
    dst = os.path.join(org_dir, f"{aid}.pdf")
    if os.path.exists(dst):
        return dst
    if USE_HARDLINKS:
        try:
            os.link(src_pdf, dst)   # Windows 需要管理员权限；若失败则复制
            return dst
        except Exception:
            pass
    shutil.copy2(src_pdf, dst)
    return dst
