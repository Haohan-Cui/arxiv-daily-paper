from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List, Tuple
import re
import shutil

from config import INSTITUTIONS_PATTERNS, MAX_PDF_PAGES_TO_SCAN, USE_HARDLINKS
from pdf_affil import extract_core_author_affiliation_text


def compile_patterns(institution_patterns: Dict[str, List[str]] | None = None):
    source = institution_patterns or INSTITUTIONS_PATTERNS
    return {
        org: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
        for org, patterns in source.items()
    }


def classify_from_pdf(
    entries: List[Dict[str, Any]],
    id2pdf: Dict[str, str],
    institution_patterns: Dict[str, List[str]] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
    buckets, _stats = classify_from_pdf_with_stats(entries, id2pdf, institution_patterns=institution_patterns)
    return buckets


def classify_from_pdf_with_stats(
    entries: List[Dict[str, Any]],
    id2pdf: Dict[str, str],
    institution_patterns: Dict[str, List[str]] | None = None,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    cpats = compile_patterns(institution_patterns)
    buckets: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    stats: Dict[str, Any] = {
        "entries": len(entries),
        "with_pdf": 0,
        "missing_pdf": 0,
        "empty_affiliation_text": 0,
        "matched_entries": 0,
        "unmatched_entries": 0,
        "matched_orgs": {},
        "entry_matches": {},
        "errors": [],
    }

    for entry in entries:
        aid = (entry.get("id") or "").split("/")[-1]
        pdf_path = id2pdf.get(aid)
        if not pdf_path or not os.path.exists(pdf_path):
            stats["missing_pdf"] += 1
            stats["errors"].append(f"missing pdf for {aid}")
            continue

        stats["with_pdf"] += 1
        authors = entry.get("authors") or []
        try:
            text = extract_core_author_affiliation_text(
                pdf_path,
                authors=authors,
                max_pages=MAX_PDF_PAGES_TO_SCAN,
            )
        except Exception as exc:
            stats["errors"].append(f"affiliation extraction failed for {aid}: {exc}")
            continue

        if not text:
            stats["empty_affiliation_text"] += 1
            continue

        matched_orgs: List[str] = []
        for org, patterns in cpats.items():
            if any(pattern.search(text) for pattern in patterns):
                buckets[org].append(entry)
                stats["matched_orgs"][org] = stats["matched_orgs"].get(org, 0) + 1
                matched_orgs.append(org)

        if matched_orgs:
            stats["matched_entries"] += 1
            stats["entry_matches"][aid] = matched_orgs
        else:
            stats["unmatched_entries"] += 1

    return buckets, stats


def place_pdf_into_org_dir(aid: str, src_pdf: str, org_dir: str) -> str | None:
    os.makedirs(org_dir, exist_ok=True)
    dst = os.path.join(org_dir, f"{aid}.pdf")
    if os.path.exists(dst):
        return dst
    if USE_HARDLINKS:
        try:
            os.link(src_pdf, dst)
            return dst
        except Exception:
            pass
    shutil.copy2(src_pdf, dst)
    return dst
