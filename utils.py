from __future__ import annotations
from datetime import datetime
from pathlib import Path
from config import LOCAL_TZ, OUT_BASE_DIR

def now_local():
    return datetime.now(LOCAL_TZ)

def date_folder(date_str: str) -> Path:
    return Path(OUT_BASE_DIR) / date_str
