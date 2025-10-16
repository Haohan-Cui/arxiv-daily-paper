# app.py
from __future__ import annotations
from typing import List, Dict
from datetime import timedelta
from pathlib import Path

from config import DRY_RUN, DEBUG, ORG_SEARCH_TERMS
from fetch_arxiv import iter_recent_cs, search_by_terms
from filters import beijing_previous_day_window, in_time_window, is_cs
from classify import group_by_org
from downloader import download_pdfs_for_org
from utils import now_local, date_folder

# 行为开关：
FILL_MISSING_BY_ORG = True     # 仅对“基线为空”的机构做直搜补齐
ALWAYS_PER_ORG_SEARCH = False  # True=对所有机构都跑直搜（与基线合并），更全但更慢

def _debug_print_window(now, start_utc, end_utc):
    if not DEBUG:
        return
    print(f"[DEBUG] now local = {now.isoformat()}")
    print(f"[DEBUG] window (UTC) = {start_utc.isoformat()}  ->  {end_utc.isoformat()}")

def _collect_baseline_entries(start_utc, end_utc) -> List[Dict]:
    """基线：拉 cs.* 多页，再本地按时间窗口过滤。"""
    entries: List[Dict] = []
    total_scanned = 0
    for e in iter_recent_cs():
        total_scanned += 1
        if is_cs(e) and in_time_window(e, start_utc, end_utc):
            entries.append(e)
    if DEBUG:
        print(f"[DEBUG] scanned={total_scanned}  baseline_matches={len(entries)}")
    return entries

def build_buckets_with_fallback(baseline_entries: List[Dict], start_utc, end_utc) -> Dict[str, List[Dict]]:
    """
    先用正则把基线 entries 分桶；
    再按机构逐个“缺啥补啥”地用 arXiv API 直搜补齐（或强制全量直搜），并与基线结果合并去重。
    """
    # 1) 基线分桶
    buckets = group_by_org(baseline_entries)
    if DEBUG:
        print(f"[DEBUG] baseline org-buckets: { {k: len(v) for k, v in buckets.items()} }")

    # 2) 决定本轮要直搜的机构
    if ALWAYS_PER_ORG_SEARCH:
        targets = list(ORG_SEARCH_TERMS.keys())
    elif FILL_MISSING_BY_ORG:
        targets = [org for org in ORG_SEARCH_TERMS.keys() if not buckets.get(org)]
    else:
        targets = [] if buckets else list(ORG_SEARCH_TERMS.keys())

    if DEBUG:
        print(f"[DEBUG] per-org search targets: {targets}")

    # 3) 对目标机构逐个直搜，并与现有桶合并去重
    for org in targets:
        terms = ORG_SEARCH_TERMS.get(org, [])
        if not terms:
            continue
        org_hits: List[Dict] = []
        for e in search_by_terms(terms, limit_pages=3, page_size=200):
            if is_cs(e) and in_time_window(e, start_utc, end_utc):
                org_hits.append(e)
        if DEBUG:
            print(f"[FALLBACK-DEBUG] {org}: found {len(org_hits)} by direct query")
        if not org_hits:
            continue
        if org not in buckets:
            buckets[org] = []
        seen = { (x.get('id') or '') for x in buckets[org] }
        for x in org_hits:
            xid = x.get('id') or ''
            if xid not in seen:
                buckets[org].append(x)
                seen.add(xid)

    return buckets

def main():
    # 1) 计算“昨天（北京时间）”的 UTC 窗口
    now = now_local()
    start_utc, end_utc = beijing_previous_day_window(now)
    _debug_print_window(now, start_utc, end_utc)

    # 2) 基线 entries
    baseline_entries = _collect_baseline_entries(start_utc, end_utc)

    # 3) 按机构分桶 + 直搜补齐
    buckets = build_buckets_with_fallback(baseline_entries, start_utc, end_utc)

    # 4) 日期目录
    report_date = (now.date() - timedelta(days=1)).isoformat()
    root_dir: Path = date_folder(report_date)
    root_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出根目录: {root_dir}  DRY_RUN={DRY_RUN}")

    # 5) 各机构目录：仅下载 PDF（不合并）
    if not buckets:
        print("昨天窗口内未匹配到目标机构/学校论文（基线 + 直搜均无）。")
        return

    for org, items in sorted(buckets.items(), key=lambda kv: kv[0].lower()):
        org_dir = root_dir / org
        print(f"[{org}] 命中 {len(items)} 篇")
        pdfs = download_pdfs_for_org(org, items, org_dir, DRY_RUN)
        print(f"[{org}] 已计划/完成下载 {len(pdfs)} 个文件 -> {org_dir}")

if __name__ == "__main__":
    main()
