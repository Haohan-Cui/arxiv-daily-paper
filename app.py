from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from affil_classify import classify_from_pdf_with_stats
from config import (
    CACHE_REPORT_DIR,
    CLASSIFY_FROM_PDF,
    DEBUG,
    INSTITUTIONS_PATTERNS,
    LOCAL_TZ,
    ORG_SEARCH_TERMS,
    PRIORITY_CATEGORIES,
    PRUNE_UNMATCHED_CACHED_PDFS,
)
from fetch_arxiv import describe_arxiv_request_state, get_arxiv_id, iter_recent_cs
from filters import (
    arxiv_day_window,
    arxiv_previous_day_window,
    in_time_window,
    is_cs,
)
from pipeline_report import PipelineReport
from prefetch import cache_pdfs_with_stats
from runtime_control import PipelineCancelled, PipelineController
from utils import now_local

BASELINE_CHECKPOINT_VERSION = "api_calendar_day_v2"
ProgressCallback = Callable[[str, str, str, float | None], None]
STAGE_SEQUENCE = [
    "time_window",
    "baseline_fetch",
    "candidate_selection",
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


def _entry_in_target_window(entry: Dict[str, Any], start_utc, end_utc) -> bool:
    published = entry.get("published")
    if not published:
        return False
    return in_time_window(entry, start_utc, end_utc)


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


def _baseline_checkpoint_path(report_date: str) -> Path:
    return Path(CACHE_REPORT_DIR) / report_date / "baseline_fetch_checkpoint.json"


def _baseline_complete_cache_path(report_date: str) -> Path:
    return Path(CACHE_REPORT_DIR) / report_date / "baseline_entries_cache.json"


def _serialize_checkpoint_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(entry)
    for key, value in list(payload.items()):
        if hasattr(value, "isoformat"):
            payload[key] = value.isoformat()
    return payload


def _deserialize_iso_datetime_fields(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(entry)
    for key in ("published", "updated"):
        value = payload.get(key)
        if isinstance(value, str):
            try:
                payload[key] = datetime.fromisoformat(value)
            except Exception:
                payload[key] = None
    return payload


def _deserialize_checkpoint_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    return _deserialize_iso_datetime_fields(entry)


def _load_baseline_checkpoint(report_date: str, start_utc, end_utc) -> Dict[str, Any] | None:
    path = _baseline_checkpoint_path(report_date)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("start_utc") != start_utc.isoformat() or payload.get("end_utc") != end_utc.isoformat():
        return None
    if payload.get("filter_version") != BASELINE_CHECKPOINT_VERSION:
        return None
    entries = [_deserialize_checkpoint_entry(entry) for entry in payload.get("entries", [])]
    stats = payload.get("stats") or {}
    return {
        "entries": entries,
        "stats": {
            "scanned": int(stats.get("scanned", 0)),
            "matched": int(stats.get("matched", len(entries))),
            "filtered_non_cs": int(stats.get("filtered_non_cs", 0)),
            "filtered_out_of_window": int(stats.get("filtered_out_of_window", 0)),
        },
        "next_start": int(payload.get("next_start", 0)),
    }


def _write_baseline_checkpoint(
    report_date: str,
    start_utc,
    end_utc,
    entries: List[Dict[str, Any]],
    stats: Dict[str, Any],
    next_start: int,
) -> None:
    path = _baseline_checkpoint_path(report_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_date": report_date,
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "next_start": next_start,
        "filter_version": BASELINE_CHECKPOINT_VERSION,
        "stats": stats,
        "entries": [_serialize_checkpoint_entry(entry) for entry in entries],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_baseline_checkpoint(report_date: str) -> None:
    try:
        _baseline_checkpoint_path(report_date).unlink(missing_ok=True)
    except Exception:
        pass


def _load_complete_baseline_cache(report_date: str, start_utc, end_utc) -> List[Dict[str, Any]] | None:
    path = _baseline_complete_cache_path(report_date)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if payload.get("start_utc") != start_utc.isoformat() or payload.get("end_utc") != end_utc.isoformat():
        return None
    if payload.get("filter_version") != BASELINE_CHECKPOINT_VERSION:
        return None
    return [_deserialize_checkpoint_entry(entry) for entry in payload.get("entries", [])]


def _write_complete_baseline_cache(report_date: str, start_utc, end_utc, entries: List[Dict[str, Any]]) -> None:
    path = _baseline_complete_cache_path(report_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "report_date": report_date,
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat(),
        "filter_version": BASELINE_CHECKPOINT_VERSION,
        "entries": [_serialize_checkpoint_entry(entry) for entry in entries],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _collect_baseline_entries(
    start_utc,
    end_utc,
    report_date: str,
    controller: PipelineController | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cached_entries = _load_complete_baseline_cache(report_date, start_utc, end_utc)
    if cached_entries is not None:
        _emit_progress(
            progress_callback,
            "baseline_fetch",
            f"using cached baseline for {report_date}: {len(cached_entries)} papers",
            "running",
            None,
        )
        return cached_entries, {
            "scanned": len(cached_entries),
            "matched": len(cached_entries),
            "filtered_non_cs": 0,
            "filtered_out_of_window": 0,
            "cache_hit": True,
        }

    entries: List[Dict[str, Any]] = []
    seen_entry_ids: set[str] = set()
    total_scanned = 0
    filtered_non_cs = 0
    filtered_out_of_window = 0
    start_offset = 0
    checkpoint = _load_baseline_checkpoint(report_date, start_utc, end_utc)
    if checkpoint:
        entries = checkpoint["entries"]
        seen_entry_ids = {get_arxiv_id(entry) for entry in entries}
        total_scanned = checkpoint["stats"]["scanned"]
        filtered_non_cs = checkpoint["stats"]["filtered_non_cs"]
        filtered_out_of_window = checkpoint["stats"]["filtered_out_of_window"]
        start_offset = checkpoint["next_start"]
        _emit_progress(
            progress_callback,
            "baseline_fetch",
            f"resuming baseline from cached progress: scanned {total_scanned} papers",
            "running",
            None,
        )
    else:
        request_state = describe_arxiv_request_state()
        proxy_label = "on" if request_state["api_proxy_forced"] else "off"
        cooldown = request_state.get("cooldown_until") or "none"
        _emit_progress(
            progress_callback,
            "baseline_fetch",
            (
                "arXiv API request mode: "
                f"endpoint={','.join(request_state['api_endpoints'])}, "
                f"proxy={proxy_label}, configured_proxy={request_state['proxy_configured']}, "
                f"cooldown_until={cooldown}, state_file={request_state['state_file']}"
            ),
            "running",
            None,
        )

    def _checkpoint_page(current_start: int, next_start: int, fetched_count: int) -> None:
        if fetched_count <= 0:
            return
        stats = {
            "scanned": total_scanned,
            "matched": len(entries),
            "filtered_non_cs": filtered_non_cs,
            "filtered_out_of_window": filtered_out_of_window,
        }
        _write_baseline_checkpoint(report_date, start_utc, end_utc, entries, stats, next_start)

    for entry in iter_recent_cs(
        start_utc=start_utc,
        end_utc=end_utc,
        start_offset=start_offset,
        on_page_complete=_checkpoint_page,
        on_request_progress=lambda message: _emit_progress(
            progress_callback,
            "baseline_fetch",
            message,
            "warning",
            None,
        ),
    ):
        _checkpoint(controller)
        total_scanned += 1
        if total_scanned % 25 == 0:
            _emit_progress(progress_callback, "baseline_fetch", f"baseline scanned {total_scanned} papers", "running", None)
        if not is_cs(entry):
            filtered_non_cs += 1
            continue
        if not _entry_in_target_window(entry, start_utc, end_utc):
            filtered_out_of_window += 1
            continue
        arxiv_id = get_arxiv_id(entry)
        if arxiv_id in seen_entry_ids:
            continue
        seen_entry_ids.add(arxiv_id)
        entries.append(entry)

    if DEBUG:
        print(f"[DEBUG] scanned={total_scanned} baseline_matches={len(entries)}")

    stats = {
        "scanned": total_scanned,
        "matched": len(entries),
        "filtered_non_cs": filtered_non_cs,
        "filtered_out_of_window": filtered_out_of_window,
        "cache_hit": False,
    }
    _write_complete_baseline_cache(report_date, start_utc, end_utc, entries)
    _clear_baseline_checkpoint(report_date)
    return entries, stats


def select_candidates(
    baseline_entries: List[Dict[str, Any]],
    progress_callback: ProgressCallback | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    _emit_progress(
        progress_callback,
        "candidate_selection",
        "calendar-day CS baseline accepted; institution matching will use cached PDFs",
        "ok",
        _stage_percent("candidate_selection"),
    )
    return list(baseline_entries), {
        "baseline_candidates": len(baseline_entries),
        "selected_candidates": len(baseline_entries),
        "selection_mode": "complete_calendar_day_cs_baseline",
    }


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
    serialized = _deserialize_iso_datetime_fields(_serialize_checkpoint_entry(entry))
    serialized = _serialize_checkpoint_entry(serialized)
    serialized["arxiv_id"] = get_arxiv_id(entry)
    serialized["cached_pdf"] = cache_path
    serialized["matched_orgs"] = matched_orgs or []
    return serialized


def write_json_outputs(report_date: str, report: PipelineReport, ordered_entries: List[Dict[str, Any]], id2pdf: Dict[str, str], matched_orgs_by_id: Dict[str, List[str]], controller: PipelineController | None = None) -> Dict[str, str]:
    _checkpoint(controller)
    if isinstance(report_date, datetime):
        report_date = report_date.astimezone(LOCAL_TZ).date().isoformat()
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
        report_date = now.astimezone(LOCAL_TZ).date() - timedelta(days=1)
        start_utc, end_utc = arxiv_previous_day_window(now)
        return start_utc, end_utc, report_date.isoformat()
    if isinstance(target_day, str):
        target_day = date.fromisoformat(target_day)
    start_utc, end_utc = arxiv_day_window(target_day)
    return start_utc, end_utc, target_day.isoformat()


def run_pipeline(
    now=None,
    target_day: date | str | None = None,
    institution_patterns: Dict[str, List[str]] | None = None,
    controller: PipelineController | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Dict[str, Any]:
    report = PipelineReport()
    result: Dict[str, Any] = {"report": report, "report_date": None, "candidates": [], "ordered_candidates": [], "filtered_candidates": [], "cached": {}, "json_outputs": {}}

    now = now or now_local()

    try:
        _begin_stage(report, "time_window", progress_callback, "calculating time window")
        _checkpoint(controller)
        start_utc, end_utc, report_date = _resolve_window(now, target_day)
        result["report_date"] = report_date
        _debug_print_window(now, start_utc, end_utc)
        _record_stage_metrics(report, "time_window", {"now": now.isoformat(), "start_utc": start_utc.isoformat(), "end_utc": end_utc.isoformat(), "report_date": report_date, "requested_date": str(target_day or report_date)})
        _finish_stage(report, "time_window", progress_callback, f"time window ready: {report_date}")

        _begin_stage(report, "baseline_fetch", progress_callback, "starting baseline fetch")
        baseline_entries, baseline_stats = _collect_baseline_entries(
            start_utc,
            end_utc,
            report_date=report_date,
            controller=controller,
            progress_callback=progress_callback,
        )
        _record_stage_metrics(report, "baseline_fetch", baseline_stats)
        if baseline_stats["matched"] == 0:
            report.stage("baseline_fetch").add_warning("baseline fetch returned no in-window papers")
        _finish_stage(report, "baseline_fetch", progress_callback, f"baseline fetch complete, matched {baseline_stats['matched']} papers")

        _begin_stage(report, "candidate_selection", progress_callback, "selecting baseline candidates")
        candidates, selection_stats = select_candidates(
            baseline_entries,
            progress_callback=progress_callback,
        )
        result["candidates"] = candidates
        _record_stage_metrics(report, "candidate_selection", selection_stats)
        if not candidates:
            report.stage("candidate_selection").add_warning("no candidates available for PDF processing")
        _finish_stage(report, "candidate_selection", progress_callback, f"candidate selection complete, total {len(candidates)} papers")

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
        result["ordered_candidates"] = [
            entry for entry in result["ordered_candidates"]
            if get_arxiv_id(entry) in id2pdf
        ]
        cache_stats["pdf_available_candidates"] = len(result["ordered_candidates"])
        _record_stage_metrics(report, "pdf_cache", cache_stats)
        for message in cache_stats["errors"][:20]:
            report.stage("pdf_cache").add_warning(message)
        if cache_stats["failed"] > 0 and cache_stats["downloaded"] == 0 and cache_stats["cache_hits"] == 0:
            report.stage("pdf_cache").add_error("all PDF cache attempts failed")
        _finish_stage(report, "pdf_cache", progress_callback, f"PDF cache complete, hits {cache_stats['cache_hits']}, downloads {cache_stats['downloaded']}, skipped small {cache_stats.get('skipped_small', 0)}")

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
        json_outputs = write_json_outputs(report_date, report, result["filtered_candidates"], id2pdf, matched_orgs_by_id, controller=controller)
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
