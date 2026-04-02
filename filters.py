from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Any, Tuple
from config import LOCAL_TZ, ARXIV_PRIMARY_CATEGORY_PREFIXES, ARXIV_EXCLUDED_CATEGORIES


def arxiv_day_window(target_day: date) -> Tuple[datetime, datetime]:
    """Return the given arXiv server calendar day (America/New_York) as a UTC window."""
    start_local = datetime.combine(target_day, datetime.min.time(), tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1) - timedelta(microseconds=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def arxiv_previous_day_window(now_local: datetime) -> Tuple[datetime, datetime]:
    """Return the previous calendar day in arXiv server time (America/New_York)."""
    local_now = now_local.astimezone(LOCAL_TZ)
    target_day = local_now.date() - timedelta(days=1)
    return arxiv_day_window(target_day)


def in_time_window(entry: Dict[str, Any], start_utc: datetime, end_utc: datetime) -> bool:
    dt = entry.get("published")
    return bool(dt and start_utc <= dt <= end_utc)


def is_cs(entry: Dict[str, Any]) -> bool:
    cat = entry.get("primary_category") or ""
    if not any(cat.startswith(prefix) for prefix in ARXIV_PRIMARY_CATEGORY_PREFIXES):
        return False
    return cat not in set(ARXIV_EXCLUDED_CATEGORIES)
