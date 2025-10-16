from __future__ import annotations
from typing import Dict, Any, List, DefaultDict
from collections import defaultdict
import re
from config import INSTITUTIONS_PATTERNS

def compile_patterns():
    return {org: [re.compile(p, re.IGNORECASE) for p in pats]
            for org, pats in INSTITUTIONS_PATTERNS.items()}

def match_orgs(entry: Dict[str, Any], compiled) -> List[str]:
    hay = "\n".join([
        entry.get("title",""),
        entry.get("summary",""),
        entry.get("comment",""),
        entry.get("journal_ref",""),
        " ".join(entry.get("authors") or []),  # 有时作者串会带单位
    ])
    hits = []
    for org, pats in compiled.items():
        if any(p.search(hay) for p in pats):
            hits.append(org)
    return hits

def group_by_org(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    compiled = compile_patterns()
    buckets: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in entries:
        for org in match_orgs(e, compiled):
            buckets[org].append(e)
    return buckets
