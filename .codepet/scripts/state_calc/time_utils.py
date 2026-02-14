"""Time and primitive conversion helpers for state calculation."""

import os
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .constants import DEFAULT_TIMEZONE


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


def get_timezone_name() -> str:
    """Resolve configured timezone name with validation and fallback."""
    candidate = os.environ.get("CODEPET_TIMEZONE", DEFAULT_TIMEZONE)
    try:
        ZoneInfo(candidate)
        return candidate
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE


def to_local_time(dt: datetime, timezone_name: str | None = None) -> datetime:
    """Convert a datetime to the configured local timezone."""
    zone_name = timezone_name or get_timezone_name()
    tz = ZoneInfo(zone_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def classify_time_of_day(local_hour: int) -> str:
    """Map local hour to a narrative bucket."""
    if 6 <= local_hour <= 11:
        return "morning"
    if 12 <= local_hour <= 17:
        return "afternoon"
    if 18 <= local_hour <= 21:
        return "evening"
    return "night"


def is_hour_in_window(local_hour: int, start_hour: int, end_hour: int) -> bool:
    """Return true if hour is inside a half-open [start, end) window with wrap support."""
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= local_hour < end_hour
    return local_hour >= start_hour or local_hour < end_hour


def interval_overlaps_local_window(
    start_utc: datetime,
    end_utc: datetime,
    timezone_name: str,
    window_start_hour: int,
    window_end_hour: int,
) -> bool:
    """
    Check whether [start_utc, end_utc] overlaps the recurring local-time window.

    Window semantics are half-open [window_start_hour, window_end_hour), with
    wrap support when end is earlier than start.
    """
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)
    if end_utc.tzinfo is None:
        end_utc = end_utc.replace(tzinfo=timezone.utc)
    if end_utc <= start_utc:
        return False

    tz = ZoneInfo(timezone_name)
    start_local = start_utc.astimezone(tz)
    end_local = end_utc.astimezone(tz)

    current_day = start_local.date()
    last_day = end_local.date()
    while current_day <= last_day:
        window_start = datetime.combine(current_day, time(hour=window_start_hour), tzinfo=tz)
        window_end = datetime.combine(current_day, time(hour=window_end_hour), tzinfo=tz)
        if window_end_hour <= window_start_hour:
            window_end += timedelta(days=1)

        overlap_start = max(start_local, window_start)
        overlap_end = min(end_local, window_end)
        if overlap_start < overlap_end:
            return True
        current_day += timedelta(days=1)

    return False


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
