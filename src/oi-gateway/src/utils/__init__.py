"""Utility functions shared across the oi-gateway package."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    """Return current UTC datetime with timezone."""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """Return current UTC time as an ISO-8601 string with millisecond precision.
    
    Format: YYYY-MM-DDTHH:MM:SS.sssZ
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def dt_to_str(dt: datetime | None) -> str | None:
    """Convert datetime to ISO string.
    
    Returns None if dt is None.
    """
    if dt is None:
        return None
    return dt.isoformat()


def str_to_dt(s: str | None) -> datetime | None:
    """Convert ISO datetime string back to datetime.
    
    Inverse of dt_to_str.
    Returns None if s is None.
    """
    if s is None:
        return None
    return datetime.fromisoformat(s)