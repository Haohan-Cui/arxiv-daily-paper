from __future__ import annotations

from datetime import datetime

from config import LOCAL_TZ


def now_local():
    return datetime.now(LOCAL_TZ)
