from __future__ import annotations

from typing import Any, Iterable, List
from pathlib import Path
from html import unescape
import re

try:
    import fitz
except ModuleNotFoundError:
    fitz = None

_AUTHOR_WINDOW_LINES = 10
_EDGE_SCAN_LINES = 12
_ABSTRACT_RE = re.compile(r"^\s*abstract\b", re.IGNORECASE)
_CORRESPONDING_RE = re.compile(r"correspond|contact|通讯|邮箱|email", re.IGNORECASE)
_AFFIL_RE = re.compile(
    r"University|Institute|Laboratory|Lab|Dept|Department|School|College|Center|Centre|Academy|"
    r"Research|Robotics|AI|Inc\.|Ltd\.|Company|作者|通讯|实验室|研究院|大学|学院|中心|公司",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _author_markers(authors: Iterable[str]) -> List[str]:
    markers: List[str] = []
    for author in list(authors)[:2]:
        clean = _normalize(author)
        if not clean:
            continue
        markers.append(clean)
        parts = clean.split()
        if parts:
            markers.append(parts[-1])
        if len(parts) >= 2:
            markers.append(" ".join(parts[-2:]))
    seen = set()
    out: List[str] = []
    for marker in markers:
        if marker and marker not in seen:
            seen.add(marker)
            out.append(marker)
    return out


def _page_lines(page: Any) -> List[str]:
    blocks = page.get_text("blocks") or []
    ordered = sorted(blocks, key=lambda b: (b[1], b[0]))
    lines: List[str] = []
    for block in ordered:
        text = (block[4] or "").strip()
        if not text:
            continue
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _ABSTRACT_RE.match(line):
                return lines
            lines.append(line)
    return lines


def _html_lines(path: str) -> List[str]:
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|section|article|h[1-6]|li|tr)>", "\n", raw)
    text = unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if _ABSTRACT_RE.match(line):
            break
        lines.append(line)
    return lines


def _find_author_anchor(lines: List[str], authors: List[str]) -> int | None:
    markers = _author_markers(authors)
    normalized_lines = [_normalize(line) for line in lines]
    for idx, line in enumerate(normalized_lines):
        if any(marker and marker in line for marker in markers):
            return idx
    return None


def _collect_candidate_lines(lines: List[str], anchor: int) -> List[str]:
    window = lines[anchor:anchor + _AUTHOR_WINDOW_LINES]
    relevant: List[str] = []
    for idx, line in enumerate(window):
        prev_line = window[idx - 1] if idx > 0 else ""
        next_line = window[idx + 1] if idx + 1 < len(window) else ""
        joined = " ".join([prev_line, line, next_line])
        if _AFFIL_RE.search(joined) or _CORRESPONDING_RE.search(joined) or "@" in joined:
            relevant.append(line)

    if not relevant:
        relevant = window[:4]
    return relevant


def _scan_top_and_bottom(lines: List[str], authors: List[str]) -> List[str]:
    anchor = _find_author_anchor(lines, authors)
    if anchor is not None:
        return _collect_candidate_lines(lines, anchor)

    edge_lines = lines[:_EDGE_SCAN_LINES] + lines[-_EDGE_SCAN_LINES:]
    edge_anchor = _find_author_anchor(edge_lines, authors)
    if edge_anchor is not None:
        return _collect_candidate_lines(edge_lines, edge_anchor)

    return _collect_candidate_lines(lines[:_EDGE_SCAN_LINES], 0)


def extract_core_author_affiliation_text(pdf_path: str, authors: List[str], max_pages: int = 1) -> str:
    """Extract affiliation cues near the first/corresponding author block on the first page.

    The scan checks both the top matter and bottom-of-page author blocks because some templates
    place affiliations in footers or bottom notes.
    """
    if Path(pdf_path).suffix.lower() in {".html", ".htm"}:
        lines = _html_lines(pdf_path)
    else:
        if fitz is None:
            raise RuntimeError("PyMuPDF (fitz) is required for PDF affiliation extraction")

        doc = fitz.open(pdf_path)
        try:
            if not len(doc):
                return ""
            lines = _page_lines(doc.load_page(0))
        finally:
            doc.close()

    if not lines:
        return ""

    relevant = _scan_top_and_bottom(lines, authors)
    return "\n".join(relevant).strip()
