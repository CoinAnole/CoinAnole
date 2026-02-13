"""Commit session analysis helpers."""

from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from .constants import (
    DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES,
    MARATHON_MIN_COMMITS,
    MARATHON_THRESHOLD_MINUTES,
    MAX_DETECTED_SESSIONS,
    SESSION_SPLIT_TIMEOUT_MINUTES_MAX,
    SESSION_SPLIT_TIMEOUT_MINUTES_MIN,
)
from .time_utils import parse_iso_datetime, to_int, to_iso8601


def _normalize_repo_list(value: Any) -> list[str]:
    """Normalize repo lists to sorted, unique non-empty strings."""
    if not isinstance(value, list):
        return []
    return sorted({
        repo for repo in value
        if isinstance(repo, str) and repo
    })


def calculate_session_duration_minutes(
    first_commit: datetime | None,
    last_commit: datetime | None,
    commit_count: int,
) -> int:
    """
    Calculate session duration from commit timestamps.

    Falls back to 10 minutes for a single commit to avoid zero-length sessions.
    """
    if commit_count <= 0 or first_commit is None or last_commit is None:
        return 0
    if commit_count == 1:
        return 10

    duration_minutes = int(round((last_commit - first_commit).total_seconds() / 60))
    return max(10, duration_minutes)


def compute_adaptive_timeout(gaps_minutes: list[float], fallback_timeout: int | None) -> int:
    """
    Compute split timeout from recent commit gaps.

    Candidate timeout is `3 * median_gap`, then bounded by:
    clamp(30, 90, max(45, candidate)).
    """
    clean_gaps = [
        float(gap)
        for gap in gaps_minutes
        if isinstance(gap, (int, float)) and gap > 0
    ]

    if clean_gaps:
        candidate = int(round(3 * median(clean_gaps)))
    elif isinstance(fallback_timeout, int) and fallback_timeout > 0:
        candidate = fallback_timeout
    else:
        candidate = DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES

    timeout = max(DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES, candidate)
    timeout = max(SESSION_SPLIT_TIMEOUT_MINUTES_MIN, timeout)
    timeout = min(SESSION_SPLIT_TIMEOUT_MINUTES_MAX, timeout)
    return timeout


def split_into_sessions(commit_events: list[dict[str, Any]], split_timeout: int) -> list[list[dict[str, Any]]]:
    """Split commit events into coherent sessions using inactivity gap threshold."""
    if not commit_events:
        return []

    def normalize_commit_time(value: Any) -> datetime | None:
        if not isinstance(value, datetime):
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    events = []
    for event in commit_events:
        commit_time = normalize_commit_time(event.get("timestamp"))
        if commit_time is None:
            continue
        events.append(
            {
                "timestamp": commit_time,
                "repo": event.get("repo"),
            }
        )
    events.sort(key=lambda event: event["timestamp"])
    if not events:
        return []

    sessions: list[list[dict[str, Any]]] = []
    current_session: list[dict[str, Any]] = []
    previous_time: datetime | None = None
    safe_timeout = max(1, split_timeout)

    for event in events:
        commit_time = event["timestamp"]

        normalized_event = {
            "timestamp": commit_time,
            "repo": event.get("repo"),
        }
        if previous_time is None:
            current_session = [normalized_event]
        else:
            gap_minutes = (commit_time - previous_time).total_seconds() / 60
            if gap_minutes > safe_timeout:
                if current_session:
                    sessions.append(current_session)
                current_session = [normalized_event]
            else:
                current_session.append(normalized_event)
        previous_time = commit_time

    if current_session:
        sessions.append(current_session)

    return sessions


def summarize_session(session_events: list[dict[str, Any]]) -> dict | None:
    """Summarize a session into API-safe primitives."""
    if not session_events:
        return None

    ordered = sorted(
        [event for event in session_events if isinstance(event.get("timestamp"), datetime)],
        key=lambda event: event["timestamp"],
    )
    if not ordered:
        return None

    first_commit = ordered[0]["timestamp"].astimezone(timezone.utc)
    last_commit = ordered[-1]["timestamp"].astimezone(timezone.utc)
    commit_count = len(ordered)
    repos_touched = sorted(
        {
            repo
            for repo in (event.get("repo") for event in ordered)
            if isinstance(repo, str) and repo
        }
    )

    return {
        "start": to_iso8601(first_commit),
        "end": to_iso8601(last_commit),
        "duration_minutes": calculate_session_duration_minutes(first_commit, last_commit, commit_count),
        "commit_count": commit_count,
        "repos_touched": repos_touched,
    }


def select_primary_session(summaries: list[dict[str, Any]]) -> dict | None:
    """
    Select the primary coherent session using tie-breakers:
    longest duration, then more commits, then latest end time.
    """
    if not summaries:
        return None

    def key(summary: dict[str, Any]) -> tuple[int, int, float]:
        duration = to_int(summary.get("duration_minutes"), 0)
        commit_count = to_int(summary.get("commit_count"), 0)
        end_dt = parse_iso_datetime(summary.get("end"))
        end_ts = end_dt.timestamp() if end_dt else 0.0
        return duration, commit_count, end_ts

    return max(summaries, key=key)


def merge_with_open_session(open_session: dict | None, first_new_commit_time: datetime | None) -> bool:
    """Return True when incoming commits continue the previous open session."""
    if not isinstance(open_session, dict) or first_new_commit_time is None:
        return False

    open_last_commit = parse_iso_datetime(open_session.get("last_commit"))
    if open_last_commit is None:
        return False
    if first_new_commit_time.tzinfo is None:
        first_new_commit_time = first_new_commit_time.replace(tzinfo=timezone.utc)
    first_new_commit_time = first_new_commit_time.astimezone(timezone.utc)

    split_timeout = max(
        1,
        to_int(open_session.get("split_timeout_minutes"), DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES),
    )
    gap_minutes = (first_new_commit_time - open_last_commit).total_seconds() / 60
    return 0 <= gap_minutes <= split_timeout


def normalize_open_session(open_session: Any) -> dict | None:
    """Normalize persisted open-session state to known-safe values."""
    if not isinstance(open_session, dict):
        return None

    start = parse_iso_datetime(open_session.get("start"))
    last_commit = parse_iso_datetime(open_session.get("last_commit"))
    if start is None or last_commit is None:
        return None

    commit_count = max(0, to_int(open_session.get("commit_count"), 0))
    if commit_count <= 0:
        return None

    repos_touched = _normalize_repo_list(open_session.get("repos_touched", []))
    split_timeout = compute_adaptive_timeout(
        gaps_minutes=[],
        fallback_timeout=to_int(open_session.get("split_timeout_minutes"), DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES),
    )

    return {
        "start": to_iso8601(start),
        "last_commit": to_iso8601(last_commit),
        "commit_count": commit_count,
        "repos_touched": repos_touched,
        "split_timeout_minutes": split_timeout,
    }


def normalize_session_tracker(session_tracker: Any) -> dict:
    """Normalize session tracker state for persistence."""
    tracker = session_tracker if isinstance(session_tracker, dict) else {}
    open_session = normalize_open_session(tracker.get("open_session"))
    last_timeout = compute_adaptive_timeout(
        gaps_minutes=[],
        fallback_timeout=to_int(tracker.get("last_timeout_minutes"), DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES),
    )
    return {
        "open_session": open_session,
        "last_timeout_minutes": last_timeout,
    }


def merge_open_session_into_summary(open_session: dict, summary: dict) -> dict:
    """Merge previous open-session summary into first new summary."""
    open_start = parse_iso_datetime(open_session.get("start"))
    open_last = parse_iso_datetime(open_session.get("last_commit"))
    summary_start = parse_iso_datetime(summary.get("start"))
    summary_end = parse_iso_datetime(summary.get("end"))
    if not all([open_start, open_last, summary_start, summary_end]):
        return summary

    merged_start = min(open_start, summary_start)
    merged_end = max(open_last, summary_end)
    merged_count = max(0, to_int(open_session.get("commit_count"), 0)) + max(
        0, to_int(summary.get("commit_count"), 0)
    )
    merged_repos = sorted(set(
        _normalize_repo_list(open_session.get("repos_touched", []))
        + _normalize_repo_list(summary.get("repos_touched", []))
    ))

    return {
        "start": to_iso8601(merged_start),
        "end": to_iso8601(merged_end),
        "duration_minutes": calculate_session_duration_minutes(merged_start, merged_end, merged_count),
        "commit_count": merged_count,
        "repos_touched": merged_repos,
    }


def analyze_commit_sessions(
    commit_events: list[dict[str, Any]],
    today: str,
    now: datetime,
    previous_session_tracker: dict | None,
) -> dict:
    """Compute coherent session summaries and tracker updates."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)

    normalized_events: list[dict[str, Any]] = []
    for event in commit_events:
        commit_time = event.get("timestamp")
        repo = event.get("repo")
        if not isinstance(commit_time, datetime):
            continue
        if commit_time.tzinfo is None:
            commit_time = commit_time.replace(tzinfo=timezone.utc)
        normalized_events.append({
            "timestamp": commit_time.astimezone(timezone.utc),
            "repo": repo if isinstance(repo, str) else None,
        })
    normalized_events.sort(key=lambda event: event["timestamp"])

    previous_tracker = normalize_session_tracker(previous_session_tracker)
    previous_open_session = previous_tracker.get("open_session")
    fallback_timeout = previous_tracker.get("last_timeout_minutes", DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES)

    gaps_minutes: list[float] = []
    for idx in range(1, len(normalized_events)):
        gap = (normalized_events[idx]["timestamp"] - normalized_events[idx - 1]["timestamp"]).total_seconds() / 60
        if gap > 0:
            gaps_minutes.append(gap)
    split_timeout = compute_adaptive_timeout(gaps_minutes, fallback_timeout)

    sessions = split_into_sessions(normalized_events, split_timeout)
    summaries = [summary for summary in (summarize_session(session) for session in sessions) if summary]

    first_new_commit_time = normalized_events[0]["timestamp"] if normalized_events else None
    should_merge_open = merge_with_open_session(previous_open_session, first_new_commit_time)
    if should_merge_open and summaries:
        summaries[0] = merge_open_session_into_summary(previous_open_session, summaries[0])

    primary_session = select_primary_session(summaries)

    today_events = [
        event for event in normalized_events
        if event["timestamp"].strftime("%Y-%m-%d") == today
    ]
    today_sessions = split_into_sessions(today_events, split_timeout)
    today_summaries = [summary for summary in (summarize_session(session) for session in today_sessions) if summary]
    today_primary_session = select_primary_session(today_summaries)

    marathon_detected = any(
        to_int(summary.get("duration_minutes"), 0) >= MARATHON_THRESHOLD_MINUTES
        and to_int(summary.get("commit_count"), 0) >= MARATHON_MIN_COMMITS
        for summary in summaries
    )

    open_session: dict | None = None
    if summaries:
        latest_summary = summaries[-1]
        latest_end = parse_iso_datetime(latest_summary.get("end"))
        if latest_end is not None and now - latest_end <= timedelta(minutes=split_timeout):
            latest_repos = latest_summary.get("repos_touched", [])
            if not isinstance(latest_repos, list):
                latest_repos = []
            open_session = {
                "start": latest_summary.get("start"),
                "last_commit": latest_summary.get("end"),
                "commit_count": max(0, to_int(latest_summary.get("commit_count"), 0)),
                "repos_touched": sorted(set(latest_repos)),
                "split_timeout_minutes": split_timeout,
            }
    elif previous_open_session:
        previous_last = parse_iso_datetime(previous_open_session.get("last_commit"))
        previous_timeout = max(
            1,
            to_int(previous_open_session.get("split_timeout_minutes"), split_timeout),
        )
        if previous_last is not None and now - previous_last <= timedelta(minutes=previous_timeout):
            open_session = previous_open_session

    session_tracker = normalize_session_tracker({
        "open_session": open_session,
        "last_timeout_minutes": split_timeout,
    })

    return {
        "session_split_timeout_minutes": split_timeout,
        "session_count_detected": len(summaries),
        "primary_session": primary_session,
        "detected_sessions": summaries[-MAX_DETECTED_SESSIONS:],
        "session_duration_minutes": to_int((primary_session or {}).get("duration_minutes"), 0),
        "session_duration_today_minutes": to_int((today_primary_session or {}).get("duration_minutes"), 0),
        "marathon_detected": marathon_detected,
        "session_tracker": session_tracker,
    }
