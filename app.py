from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from affil_classify import classify_from_pdf_with_stats
from config import (
    CACHE_REPORT_DIR,
    CLASSIFY_FROM_PDF,
    DEBUG,
    FALLBACK_SKIP_IF_BASELINE_AT_LEAST,
    INSTITUTIONS_PATTERNS,
    LOCAL_TZ,
    ORG_SEARCH_TERMS,
    PER_ORG_SEARCH_LIMIT_PAGES,
    PER_ORG_SEARCH_PAGE_SIZE,
    PRIORITY_CATEGORIES,
    PRUNE_UNMATCHED_CACHED_PDFS,
)
from fetch_arxiv import get_arxiv_id, iter_recent_cs, search_by_terms
from filters import arxiv_day_window, arxiv_previous_day_window, in_time_window, is_cs
from pipeline_report import PipelineReport
from prefetch import cache_pdfs_with_stats
from runtime_control import PipelineCancelled, PipelineController
from utils import now_local

FILL_MISSING_BY_ORG = True
ALWAYS_PER_ORG_SEARCH = False
ProgressCallback = Callable[[str, str, str, float | None], None]
STAGE_SEQUENCE = [
    "time_window",
    "baseline_fetch",
    "fallback_merge",
    "priority_ranking",
    "pdf_cache",
    "author_affiliation_filter",
    "cache_cleanup",
    "report_output",
]


def _emit_progress(callback: ProgressCallback | None, stage: str, message: str, state: str = "info", percent: float | None = None) -> None:
    if callback:
        callback(stage, message, state, percent)


def _checkpoint(controller: PipelineController | None) -> None:
    if controller:
        controller.checkpoint()


def _stage_percent(stage_name: str) -> float:
    try:
        return (STAGE_SEQUENCE.index(stage_name) / max(len(STAGE_SEQUENCE) - 1, 1)) * 100.0
    except ValueError:
        return 0.0


def _begin_stage(report: PipelineReport, stage_name: str, callback: ProgressCallback | None, message: str) -> None:
    report.stage(stage_name).start()
    _emit_progress(callback, stage_name, message, "running", _stage_percent(stage_name))


def _finish_stage(report: PipelineReport, stage_name: str, callback: ProgressCallback | None, message: str) -> None:
    stage = report.stage(stage_name)
    status = "error" if stage.errors else "warning" if stage.warnings else "ok"
    stage.finish(status)
    _emit_progress(callback, stage_name, message, status, _stage_percent(stage_name))


def _debug_print_window(now, start_utc, end_utc):
    if not DEBUG:
        return
    print(f"[DEBUG] now local = {now.isoformat()}")
    print(f"[DEBUG] window (UTC) = {start_utc.isoformat()}  ->  {end_utc.isoformat()}")


def _normalize_term(term: str) -> str:
    return term.strip().strip('"').strip()


def _search_term_for_query(term: str) -> str:
    clean = _normalize_term(term)
    if not clean:
        return ""
    if re.search(r"\s", clean):
        return f'"{clean}"'
    return clean


def _pattern_for_term(term: str) -> str:
    clean = _normalize_term(term)
    if not clean:
        return ""
    escaped = re.escape(clean).replace(r"\ ", r"\s*")
    if re.search(r"[A-Za-z0-9]", clean):
        return rf"\b{escaped}\b"
    return escaped


def parse_institutions_text(text: str) -> List[Dict[str, List[str]]]:
    parsed: List[Dict[str, List[str]]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line:
            name, aliases_raw = line.split(":", 1)
            aliases = [_normalize_term(part) for part in aliases_raw.split(",")]
        else:
            name = line
            aliases = [_normalize_term(line)]
        org_name = name.strip()
        aliases = [alias for alias in aliases if alias]
        if not org_name or not aliases:
            continue
        parsed.append({"name": org_name, "terms": aliases})
    return parsed


def build_runtime_institution_maps(custom_entries: List[Dict[str, List[str]]] | None = None) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    org_search_terms = {org: list(terms) for org, terms in ORG_SEARCH_TERMS.items()}
    institution_patterns = {org: [pattern for pattern in patterns] for org, patterns in INSTITUTIONS_PATTERNS.items()}

    for entry in custom_entries or []:
        org = entry["name"]
        terms = [_normalize_term(term) for term in entry.get("terms", []) if _normalize_term(term)]
        if not terms:
            continue
        org_search_terms[org] = [_search_term_for_query(term) for term in terms if _search_term_for_query(term)]
        institution_patterns[org] = [_pattern_for_term(term) for term in terms if _pattern_for_term(term)]
    return org_search_terms, institution_patterns


def institutions_text_from_terms(org_search_terms: Dict[str, List[str]] | None = None) -> str:
    source = org_search_terms or ORG_SEARCH_TERMS
    lines: List[str] = []
    for org in sorted(source):
        terms = [_normalize_term(term) for term in source[org]]
        visible_terms = []
        seen = set()
        for term in terms:
            if term and term not in seen:
                seen.add(term)
                visible_terms.append(term)
        lines.append(f"{org}: {', '.join(visible_terms)}")
    return "\n".join(lines)


def _collect_baseline_entries(start_utc, end_utc, controller: PipelineController | None = None, progress_callback: ProgressCallback | None = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    total_scanned = 0
    filtered_non_cs = 0
    filtered_out_of_window = 0

    for entry in iter_recent_cs(start_utc=start_utc):
        _checkpoint(controller)
        total_scanned += 1
        if total_scanned % 25 == 0:
            _emit_progress(progress_callback, "baseline_fetch", f"baseline scanned {total_scanned} papers", "running", None)
        if not is_cs(entry):
            filtered_non_cs += 1
            continue
        if not in_time_window(entry, start_utc, end_utc):
            filtered_out_of_window += 1
            continue
        entries.append(entry)

    if DEBUG:
        print(f"[DEBUG] scanned={total_scanned} baseline_matches={len(entries)}")

    stats = {
        "scanned": total_scanned,
        "matched": len(entries),
        "filtered_non_cs": filtered_non_cs,
        "filtered_out_of_window": filtered_out_of_window,
    }
    return entries, stats


def build_candidates_with_fallback(
    baseline_entries: List[Dict[str, Any]],
    start_utc,
    end_utc,
    org_search_terms: Dict[str, List[str]] | None = None,
    controller: PipelineController | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    org_search_terms = org_search_terms or ORG_SEARCH_TERMS
    rough_hits = set()
    for entry in baseline_entries:
        text = "\n".join([
            entry.get("title", ""),
            entry.get("summary", ""),
            entry.get("comment", ""),
            entry.get("journal_ref", ""),
            " ".join(entry.get("authors") or []),
        ])
        lowered = text.lower()
        for org, terms in org_search_terms.items():
            normalized_terms = [_normalize_term(term).lower() for term in terms]
            if any(term and term in lowered for term in normalized_terms):
                rough_hits.add(org)

    if FALLBACK_SKIP_IF_BASELINE_AT_LEAST and len(baseline_entries) >= FALLBACK_SKIP_IF_BASELINE_AT_LEAST:
        if DEBUG:
            print(f"[DEBUG] skip per-org fallback: baseline_entries={len(baseline_entries)} >= {FALLBACK_SKIP_IF_BASELINE_AT_LEAST}")
        _emit_progress(progress_callback, "fallback_merge", "skip org fallback because baseline is already large", "ok", _stage_percent("fallback_merge"))
        return list(baseline_entries), {
            "baseline_candidates": len(baseline_entries),
            "rough_hit_orgs": len(rough_hits),
            "fallback_targets": 0,
            "merged_candidates": len(baseline_entries),
            "per_org": {},
            "fallback_skipped": True,
            "configured_orgs": len(org_search_terms),
        }

    if ALWAYS_PER_ORG_SEARCH:
        targets = list(org_search_terms.keys())
    elif FILL_MISSING_BY_ORG:
        targets = [org for org in org_search_terms.keys() if org not in rough_hits]
    else:
        targets = [] if rough_hits else list(org_search_terms.keys())

    if DEBUG:
        print(f"[DEBUG] per-org search targets: {targets}")

    merged = list(baseline_entries)
    seen_ids = {(entry.get('id') or '') for entry in merged}
    per_org_stats: Dict[str, Dict[str, int]] = {}
    total_targets = len(targets) or 1

    for index, org in enumerate(targets, start=1):
        _checkpoint(controller)
        _emit_progress(progress_callback, "fallback_merge", f"org fallback {index}/{len(targets)}: {org}", "running", (index / total_targets) * 100.0)
        terms = org_search_terms.get(org, [])
        if not terms:
            continue

        raw_list = list(search_by_terms(terms, limit_pages=PER_ORG_SEARCH_LIMIT_PAGES, page_size=PER_ORG_SEARCH_PAGE_SIZE, start_utc=start_utc))
        after_window = [entry for entry in raw_list if is_cs(entry) and in_time_window(entry, start_utc, end_utc)]
        before = len(merged)
        for entry in after_window:
            xid = entry.get("id") or ""
            if xid not in seen_ids:
                merged.append(entry)
                seen_ids.add(xid)
        added = len(merged) - before
        per_org_stats[org] = {"raw": len(raw_list), "in_window": len(after_window), "added": added}

        if DEBUG:
            print(f"[FALLBACK-DEBUG] {org}: raw={len(raw_list)}, in_window={len(after_window)}, added={added}, merged total now {len(merged)}")

    stats = {
        "baseline_candidates": len(baseline_entries),
        "rough_hit_orgs": len(rough_hits),
        "fallback_targets": len(targets),
        "merged_candidates": len(merged),
        "per_org": per_org_stats,
        "fallback_skipped": False,
        "configured_orgs": len(org_search_terms),
    }
    return merged, stats


def prioritize_candidates(entries: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    priority_index = {category: idx for idx, category in enumerate(PRIORITY_CATEGORIES)}

    def sort_key(entry: Dict[str, Any]):
        category = entry.get("primary_category") or ""
        published = entry.get("published")
        published_ts = -published.timestamp() if published else float("inf")
        return (0 if category in priority_index else 1, priority_index.get(category, len(priority_index)), published_ts, get_arxiv_id(entry))

    ordered = sorted(entries, key=sort_key)
    counts = {category: 0 for category in PRIORITY_CATEGORIES}
    priority_entries = 0
    for entry in ordered:
        category = entry.get("primary_category") or ""
        if category in counts:
            counts[category] += 1
            priority_entries += 1

    stats = {
        "total": len(entries),
        "priority_entries": priority_entries,
        "non_priority_entries": len(entries) - priority_entries,
        "priority_counts": counts,
    }
    return ordered, stats


def filter_candidates_by_author_affiliation(
    ordered_entries: List[Dict[str, Any]],
    id2pdf: Dict[str, str],
    institution_patterns: Dict[str, List[str]] | None = None,
    controller: PipelineController | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    _checkpoint(controller)
    _emit_progress(progress_callback, "author_affiliation_filter", f"start author affiliation filtering for {len(ordered_entries)} papers", "running", _stage_percent("author_affiliation_filter"))
    if not CLASSIFY_FROM_PDF:
        stats = {"entries": len(ordered_entries), "matched_entries": len(ordered_entries), "unmatched_entries": 0, "matched_orgs": {}, "entry_matches": {}, "errors": [], "filter_disabled": True}
        return ordered_entries, stats

    _buckets, classify_stats = classify_from_pdf_with_stats(ordered_entries, id2pdf, institution_patterns=institution_patterns)
    matched_map = classify_stats.get("entry_matches", {})
    filtered = [entry for entry in ordered_entries if get_arxiv_id(entry) in matched_map]
    classify_stats["kept_entries"] = len(filtered)
    classify_stats["removed_entries"] = len(ordered_entries) - len(filtered)
    classify_stats["filter_disabled"] = False
    _emit_progress(progress_callback, "author_affiliation_filter", f"author affiliation filtering finished, kept {len(filtered)} papers", "ok", _stage_percent("author_affiliation_filter"))
    return filtered, classify_stats


def prune_unmatched_cached_pdfs(ordered_entries: List[Dict[str, Any]], kept_entries: List[Dict[str, Any]], id2pdf: Dict[str, str], controller: PipelineController | None = None) -> Dict[str, Any]:
    kept_ids = {get_arxiv_id(entry) for entry in kept_entries}
    removed = 0
    missing = 0
    errors: List[str] = []

    for entry in ordered_entries:
        _checkpoint(controller)
        aid = get_arxiv_id(entry)
        if aid in kept_ids:
            continue
        path = id2pdf.get(aid)
        if not path:
            missing += 1
            continue
        try:
            pdf_path = Path(path)
            if pdf_path.exists():
                pdf_path.unlink()
                removed += 1
        except Exception as exc:
            errors.append(f"failed to remove {aid}: {exc}")

    return {"removed_cached_pdfs": removed, "missing_cached_pdfs": missing, "errors": errors}


def _record_stage_metrics(report: PipelineReport, stage_name: str, metrics: Dict[str, Any]) -> None:
    stage = report.stage(stage_name)
    for key, value in metrics.items():
        stage.set_metric(key, value)


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _serialize_entry(entry: Dict[str, Any], cache_path: str | None = None, matched_orgs: List[str] | None = None) -> Dict[str, Any]:
    serialized = dict(entry)
    if isinstance(serialized.get("published"), datetime):
        serialized["published"] = serialized["published"].isoformat()
    if isinstance(serialized.get("updated"), datetime):
        serialized["updated"] = serialized["updated"].isoformat()
    serialized["arxiv_id"] = get_arxiv_id(entry)
    serialized["cached_pdf"] = cache_path
    serialized["matched_orgs"] = matched_orgs or []
    return serialized


def write_json_outputs(start_utc, report: PipelineReport, ordered_entries: List[Dict[str, Any]], id2pdf: Dict[str, str], matched_orgs_by_id: Dict[str, List[str]], controller: PipelineController | None = None) -> Dict[str, str]:
    _checkpoint(controller)
    report_date = start_utc.astimezone(LOCAL_TZ).date().isoformat()
    report_dir = Path(CACHE_REPORT_DIR) / report_date
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "pipeline_report.json"
    manifest_path = report_dir / "cache_manifest.json"

    manifest = {
        "report_date": report_date,
        "priority_categories": PRIORITY_CATEGORIES,
        "papers": [_serialize_entry(entry, id2pdf.get(get_arxiv_id(entry)), matched_orgs_by_id.get(get_arxiv_id(entry), [])) for entry in ordered_entries],
    }

    report_payload = report.to_dict()
    report_payload["report_date"] = report_date
    report_payload["priority_categories"] = PRIORITY_CATEGORIES

    report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return {"report": str(report_path), "manifest": str(manifest_path)}


def _resolve_window(now: datetime, target_day: date | str | None):
    if target_day is None:
        return arxiv_previous_day_window(now)
    if isinstance(target_day, str):
        target_day = date.fromisoformat(target_day)
    return arxiv_day_window(target_day)


def run_pipeline(
    now=None,
    target_day: date | str | None = None,
    org_search_terms: Dict[str, List[str]] | None = None,
    institution_patterns: Dict[str, List[str]] | None = None,
    controller: PipelineController | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Dict[str, Any]:
    report = PipelineReport()
    result: Dict[str, Any] = {"report": report, "report_date": None, "candidates": [], "ordered_candidates": [], "filtered_candidates": [], "cached": {}, "json_outputs": {}}

    now = now or now_local()
    org_search_terms = org_search_terms or ORG_SEARCH_TERMS

    try:
        _begin_stage(report, "time_window", progress_callback, "calculating time window")
        _checkpoint(controller)
        start_utc, end_utc = _resolve_window(now, target_day)
        report_date = start_utc.astimezone(LOCAL_TZ).date().isoformat()
        result["report_date"] = report_date
        _debug_print_window(now, start_utc, end_utc)
        _record_stage_metrics(report, "time_window", {"now": now.isoformat(), "start_utc": start_utc.isoformat(), "end_utc": end_utc.isoformat(), "report_date": report_date, "requested_date": str(target_day or report_date)})
        _finish_stage(report, "time_window", progress_callback, f"time window ready: {report_date}")

        _begin_stage(report, "baseline_fetch", progress_callback, "starting baseline fetch")
        baseline_entries, baseline_stats = _collect_baseline_entries(start_utc, end_utc, controller=controller, progress_callback=progress_callback)
        _record_stage_metrics(report, "baseline_fetch", baseline_stats)
        if baseline_stats["matched"] == 0:
            report.stage("baseline_fetch").add_warning("baseline fetch returned no in-window papers")
        _finish_stage(report, "baseline_fetch", progress_callback, f"baseline fetch complete, matched {baseline_stats['matched']} papers")

        _begin_stage(report, "fallback_merge", progress_callback, "starting org fallback merge")
        candidates, fallback_stats = build_candidates_with_fallback(baseline_entries, start_utc, end_utc, org_search_terms=org_search_terms, controller=controller, progress_callback=progress_callback)
        result["candidates"] = candidates
        _record_stage_metrics(report, "fallback_merge", fallback_stats)
        if not candidates:
            report.stage("fallback_merge").add_warning("no candidates remained after fallback merge")
        _finish_stage(report, "fallback_merge", progress_callback, f"candidate merge complete, total {len(candidates)} papers")

        _begin_stage(report, "priority_ranking", progress_callback, "starting priority ranking")
        _checkpoint(controller)
        ordered_candidates, priority_stats = prioritize_candidates(result["candidates"])
        result["ordered_candidates"] = ordered_candidates
        _record_stage_metrics(report, "priority_ranking", priority_stats)
        if priority_stats["priority_entries"] == 0:
            report.stage("priority_ranking").add_warning("no priority-category papers found in this run")
        _finish_stage(report, "priority_ranking", progress_callback, f"priority ranking complete, {priority_stats['priority_entries']} priority papers")

        _begin_stage(report, "pdf_cache", progress_callback, "starting PDF cache")
        id2pdf, cache_stats = cache_pdfs_with_stats(result["ordered_candidates"], report_date=report_date, controller=controller, progress_callback=progress_callback)
        result["cached"] = id2pdf
        _record_stage_metrics(report, "pdf_cache", cache_stats)
        for message in cache_stats["errors"][:20]:
            report.stage("pdf_cache").add_warning(message)
        if cache_stats["failed"] > 0 and cache_stats["downloaded"] == 0 and cache_stats["cache_hits"] == 0:
            report.stage("pdf_cache").add_error("all PDF cache attempts failed")
        _finish_stage(report, "pdf_cache", progress_callback, f"PDF cache complete, hits {cache_stats['cache_hits']}, downloads {cache_stats['downloaded']}")

        _begin_stage(report, "author_affiliation_filter", progress_callback, "starting author affiliation filter")
        filtered_candidates, author_stats = filter_candidates_by_author_affiliation(result["ordered_candidates"], id2pdf, institution_patterns=institution_patterns, controller=controller, progress_callback=progress_callback)
        result["filtered_candidates"] = filtered_candidates
        _record_stage_metrics(report, "author_affiliation_filter", author_stats)
        for message in author_stats.get("errors", [])[:20]:
            report.stage("author_affiliation_filter").add_warning(message)
        if author_stats.get("kept_entries", 0) == 0:
            report.stage("author_affiliation_filter").add_warning("no papers passed the lead/corresponding author affiliation filter")
        _finish_stage(report, "author_affiliation_filter", progress_callback, f"author affiliation filter complete, kept {len(filtered_candidates)} papers")

        _begin_stage(report, "cache_cleanup", progress_callback, "starting cache cleanup")
        cleanup_stats = {"removed_cached_pdfs": 0, "missing_cached_pdfs": 0, "errors": [], "cleanup_enabled": PRUNE_UNMATCHED_CACHED_PDFS}
        if PRUNE_UNMATCHED_CACHED_PDFS:
            cleanup_stats = prune_unmatched_cached_pdfs(result["ordered_candidates"], result["filtered_candidates"], id2pdf, controller=controller)
            cleanup_stats["cleanup_enabled"] = True
        _record_stage_metrics(report, "cache_cleanup", cleanup_stats)
        for message in cleanup_stats.get("errors", [])[:20]:
            report.stage("cache_cleanup").add_warning(message)
        _finish_stage(report, "cache_cleanup", progress_callback, f"cache cleanup complete, removed {cleanup_stats['removed_cached_pdfs']} PDFs")

        _begin_stage(report, "report_output", progress_callback, "writing JSON outputs")
        matched_orgs_by_id = author_stats.get("entry_matches", {})
        json_outputs = write_json_outputs(start_utc, report, result["filtered_candidates"], id2pdf, matched_orgs_by_id, controller=controller)
        result["json_outputs"] = json_outputs
        _record_stage_metrics(report, "report_output", json_outputs)
        _finish_stage(report, "report_output", progress_callback, "JSON outputs written")
        _emit_progress(progress_callback, "pipeline", "pipeline finished", "ok", 100.0)
        return result
    except PipelineCancelled:
        _emit_progress(progress_callback, "pipeline", "pipeline cancelled", "cancelled", None)
        raise
    except Exception as exc:
        _emit_progress(progress_callback, "pipeline", f"pipeline failed: {exc}", "error", None)
        raise


def print_report(report: PipelineReport) -> None:
    for line in report.summary_lines():
        print(line)


def main() -> Dict[str, Any]:
    result = run_pipeline()
    print_report(result["report"])
    for label, path in result.get("json_outputs", {}).items():
        print(f"[REPORT] wrote {label}: {path}")
    return result


if __name__ == "__main__":
    main()
