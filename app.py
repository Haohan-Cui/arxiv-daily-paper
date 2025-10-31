# app.py
from __future__ import annotations
from typing import List, Dict
from datetime import timedelta
from pathlib import Path

from config import (
    DRY_RUN, DEBUG, CLASSIFY_FROM_PDF,
    ORG_SEARCH_TERMS,
    PER_ORG_SEARCH_LIMIT_PAGES, PER_ORG_SEARCH_PAGE_SIZE,  # ← 新增：来自 config.py 的直搜深度
)
from fetch_arxiv import iter_recent_cs, search_by_terms, get_arxiv_id
from filters import beijing_previous_day_window, in_time_window, is_cs
from classify import group_by_org                   # 备用：摘要/标题粗分
from prefetch import cache_pdfs
from affil_classify import classify_from_pdf, place_pdf_into_org_dir
from utils import now_local, date_folder

# 行为开关
FILL_MISSING_BY_ORG = True       # 仅对“基线为空”的机构直搜补齐（更快）
ALWAYS_PER_ORG_SEARCH = False    # True=所有机构都跑直搜（更全但更慢）

def _debug_print_window(now, start_utc, end_utc):
    if not DEBUG:
        return
    print(f"[DEBUG] now local = {now.isoformat()}")
    print(f"[DEBUG] window (UTC) = {start_utc.isoformat()}  ->  {end_utc.isoformat()}")

def _collect_baseline_entries(start_utc, end_utc) -> List[Dict]:
    """
    基线：遍历 cs.* 多页（由 fetch_arxiv 按 config 控制分页），再按时间窗口过滤。
    新增：传入 start_utc，让 iter_recent_cs 能在遇到旧论文时提前中断。
    """
    entries: List[Dict] = []
    total_scanned = 0
    for e in iter_recent_cs(start_utc=start_utc):   # ✅ 这里传入 start_utc
        total_scanned += 1
        if is_cs(e) and in_time_window(e, start_utc, end_utc):
            entries.append(e)
    if DEBUG:
        print(f"[DEBUG] scanned={total_scanned}  baseline_matches={len(entries)}")
    return entries


def build_candidates_with_fallback(baseline_entries: List[Dict], start_utc, end_utc) -> List[Dict]:
    """
    1) 用摘要/标题对 baseline 做粗分（只为确定需要直搜的机构，不用于最终分类）。
    2) 对选定机构逐个执行 per-org 直搜（可配置深度），合并去重，返回候选列表。
       —— 诊断日志：raw（直搜返回总数）、in_window（落在窗口的）、added（真正新增）。
    """
    rough = group_by_org(baseline_entries)
    if DEBUG:
        print(f"[DEBUG] baseline org-buckets(rough): { {k: len(v) for k, v in rough.items()} }")

    if ALWAYS_PER_ORG_SEARCH:
        targets = list(ORG_SEARCH_TERMS.keys())
    elif FILL_MISSING_BY_ORG:
        targets = [org for org in ORG_SEARCH_TERMS.keys() if not rough.get(org)]
    else:
        targets = [] if rough else list(ORG_SEARCH_TERMS.keys())

    if DEBUG:
        print(f"[DEBUG] per-org search targets: {targets}")

    merged = list(baseline_entries)
    seen_ids = { (e.get("id") or "") for e in merged }

    for org in targets:
        terms = ORG_SEARCH_TERMS.get(org, [])
        if not terms:
            continue

        # —— 可调直搜深度：完全由 config 控制
        raw_list = list(search_by_terms(
            terms,
            limit_pages=PER_ORG_SEARCH_LIMIT_PAGES,
            page_size=PER_ORG_SEARCH_PAGE_SIZE
        ))
        total_raw = len(raw_list)

        # 窗口过滤（保留 cs.*）
        after_window = [e for e in raw_list if is_cs(e) and in_time_window(e, start_utc, end_utc)]
        total_window = len(after_window)

        # 合并去重
        before = len(merged)
        for e in after_window:
            xid = e.get("id") or ""
            if xid not in seen_ids:
                merged.append(e)
                seen_ids.add(xid)
        added = len(merged) - before

        if DEBUG:
            print(f"[FALLBACK-DEBUG] {org}: raw={total_raw}, in_window={total_window}, added={added}, merged total now {len(merged)}")

    return merged

def main():
    # 1) 时间窗口（昨天：北京时间）
    now = now_local()
    start_utc, end_utc = beijing_previous_day_window(now)
    _debug_print_window(now, start_utc, end_utc)

    # 2) 候选集 = 基线 +（按需）per-org 直搜补齐
    baseline_entries = _collect_baseline_entries(start_utc, end_utc)
    candidates = build_candidates_with_fallback(baseline_entries, start_utc, end_utc)
    if DEBUG:
        print(f"[DEBUG] candidates after fallback merge: {len(candidates)}")

    if not candidates:
        print("昨天窗口内没有候选论文（基线 + 直搜均为空）。")
        return

    # 3) 统一缓存 PDF（避免分类前就分散下载）
    id2pdf = cache_pdfs(candidates)

    # 4) 最终分类：优先从 PDF 的作者/单位区进行机构匹配
    if CLASSIFY_FROM_PDF:
        buckets = classify_from_pdf(candidates, id2pdf)
    else:
        buckets = group_by_org(candidates)

    # 5) 输出到日期/机构目录（硬链接或复制）
    report_date = (now.date() - timedelta(days=1)).isoformat()
    root_dir: Path = date_folder(report_date)
    root_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出根目录: {root_dir}  DRY_RUN={DRY_RUN}")

    if not buckets:
        print("昨天窗口内未匹配到目标机构/学校论文（注意：PDF作者/单位区匹配可能抽取不到文本的论文已被跳过）。")
        return

    placed = 0
    for org, items in sorted(buckets.items(), key=lambda kv: kv[0].lower()):
        org_dir = str(root_dir / org)
        print(f"[{org}] PDF 命中 {len(items)} 篇")
        if DRY_RUN:
            for e in items:
                aid = get_arxiv_id(e)
                print(f"[DRY-RUN] would place {aid}.pdf -> {org_dir}")
            continue
        for e in items:
            aid = get_arxiv_id(e)
            src = id2pdf.get(aid)
            if not src:
                continue
            dst = place_pdf_into_org_dir(aid, src, org_dir)
            if dst:
                placed += 1

    if not DRY_RUN:
        print(f"[DONE] 已放置 PDF {placed} 个到 {root_dir}")

if __name__ == "__main__":
    main()
