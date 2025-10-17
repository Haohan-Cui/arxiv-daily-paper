# pdf_affil.py
from __future__ import annotations
from typing import Optional
import fitz  # PyMuPDF

def extract_affiliation_text(pdf_path: str, max_pages: int = 2) -> str:
    """
    只读取 PDF 前 max_pages 页，把可能出现的“作者+单位”区块抽出。
    采用简单启发式：取顶部大块文本 + 包含逗号/上标数字/单位关键词的行。
    """
    doc = fitz.open(pdf_path)
    text_chunks = []

    n = min(len(doc), max_pages if max_pages > 0 else 1)
    for i in range(n):
        page = doc.load_page(i)
        # 直接用简单的文本抽取（保留换行），适配大多数 arXiv 论文
        raw = page.get_text("text")
        if not raw:
            continue
        lines = raw.splitlines()
        filtered = []
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            # 启发式：作者/单位区常含逗号、上标数字、“University/Institute/Lab”等关键词
            if ("," in s) or ("University" in s) or ("Institute" in s) or ("Laboratory" in s) \
               or ("Lab" in s) or ("Dept" in s) or ("Department" in s) \
               or any(ch in s for ch in ["¹","²","³","⁴","^1","^2","^3"]):
                filtered.append(s)
        if filtered:
            text_chunks.append("\n".join(filtered))

    doc.close()
    return "\n".join(text_chunks).strip()
