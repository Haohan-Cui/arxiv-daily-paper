from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Tuple
from config import LOCAL_TZ, ARXIV_CATEGORIES

def beijing_previous_day_window(now_local: datetime) -> Tuple[datetime, datetime]:
    prev_date = (now_local.date() - timedelta(days=1))
    start_local = datetime.combine(prev_date, datetime.min.time()).replace(tzinfo=LOCAL_TZ)
    end_local   = datetime.combine(prev_date, datetime.max.time()).replace(tzinfo=LOCAL_TZ)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

def in_time_window(entry: Dict[str, Any], start_utc: datetime, end_utc: datetime) -> bool:
    dt = entry.get("updated") or entry.get("published")
    return bool(dt and start_utc <= dt <= end_utc)

def is_cs(entry: Dict[str, Any]) -> bool:
    cat = entry.get("primary_category") or ""
    return any(cat.startswith(p) for p in ARXIV_CATEGORIES)
