"""Time and primitive conversion helpers for state calculation."""

from datetime import datetime, timezone
from typing import Any


def to_iso8601(dt: datetime | None) -> str | None:
    """Convert datetime to ISO string (UTC) if present."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def get_current_time() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def get_today_date() -> str:
    """Get today's date as ISO format string (YYYY-MM-DD)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string into timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_int(value: Any, default: int = 0) -> int:
    """Best-effort integer conversion with sane fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
