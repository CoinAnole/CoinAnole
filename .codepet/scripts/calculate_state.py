#!/usr/bin/env python3
"""
CodePet State Calculator

Scans watched repositories for activity and calculates pet state.
Writes activity.json and state.json files.

Environment Variables:
    GH_TOKEN: GitHub API token
    WATCHED_REPOS: Comma-separated list of repos to watch (e.g., "user/repo1,user/repo2")
    GITHUB_REPOSITORY: Current repo (set by GitHub Actions)
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

# Optional import - only needed if PyGithub is available
try:
    from github import Github
    HAS_GITHUB = True
except ImportError:
    HAS_GITHUB = False
    print("Warning: PyGithub not installed, activity detection will be limited")


# Default stats for new pets
DEFAULT_PET_STATS = {
    "hunger": 50,
    "energy": 50,
    "happiness": 50,
    "social": 50
}

DEFAULT_REGROUND_THRESHOLD = 6
RECENT_ACTIVE_DAYS_LIMIT = 7
DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES = 45
SESSION_SPLIT_TIMEOUT_MINUTES_MIN = 30
SESSION_SPLIT_TIMEOUT_MINUTES_MAX = 90
MARATHON_THRESHOLD_MINUTES = 120
MARATHON_MIN_COMMITS = 3
MAX_DETECTED_SESSIONS = 5


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


def calculate_session_duration_minutes(
    first_commit: datetime | None,
    last_commit: datetime | None,
    commit_count: int
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

    events = sorted(
        [
            event for event in commit_events
            if isinstance(event.get("timestamp"), datetime)
        ],
        key=lambda event: event.get("timestamp"),
    )
    if not events:
        return []

    sessions: list[list[dict[str, Any]]] = []
    current_session: list[dict[str, Any]] = []
    previous_time: datetime | None = None
    safe_timeout = max(1, split_timeout)

    for event in events:
        commit_time = event.get("timestamp")
        if not isinstance(commit_time, datetime):
            continue
        if commit_time.tzinfo is None:
            commit_time = commit_time.replace(tzinfo=timezone.utc)
        commit_time = commit_time.astimezone(timezone.utc)

        normalized_event = {
            "timestamp": commit_time,
            "repo": event.get("repo")
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
    repos_touched = sorted({
        repo for repo in (event.get("repo") for event in ordered) if isinstance(repo, str) and repo
    })

    return {
        "start": to_iso8601(first_commit),
        "end": to_iso8601(last_commit),
        "duration_minutes": calculate_session_duration_minutes(first_commit, last_commit, commit_count),
        "commit_count": commit_count,
        "repos_touched": repos_touched
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
        to_int(open_session.get("split_timeout_minutes"), DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES)
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

    raw_repos = open_session.get("repos_touched", [])
    if not isinstance(raw_repos, list):
        raw_repos = []
    repos_touched = sorted({
        repo for repo in raw_repos
        if isinstance(repo, str) and repo
    })
    split_timeout = compute_adaptive_timeout(
        gaps_minutes=[],
        fallback_timeout=to_int(open_session.get("split_timeout_minutes"), DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES)
    )

    return {
        "start": to_iso8601(start),
        "last_commit": to_iso8601(last_commit),
        "commit_count": commit_count,
        "repos_touched": repos_touched,
        "split_timeout_minutes": split_timeout
    }


def normalize_session_tracker(session_tracker: Any) -> dict:
    """Normalize session tracker state for persistence."""
    tracker = session_tracker if isinstance(session_tracker, dict) else {}
    open_session = normalize_open_session(tracker.get("open_session"))
    last_timeout = compute_adaptive_timeout(
        gaps_minutes=[],
        fallback_timeout=to_int(tracker.get("last_timeout_minutes"), DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES)
    )
    return {
        "open_session": open_session,
        "last_timeout_minutes": last_timeout
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
    open_repos = open_session.get("repos_touched", [])
    if not isinstance(open_repos, list):
        open_repos = []
    summary_repos = summary.get("repos_touched", [])
    if not isinstance(summary_repos, list):
        summary_repos = []
    merged_repos = sorted(set(open_repos + summary_repos))

    return {
        "start": to_iso8601(merged_start),
        "end": to_iso8601(merged_end),
        "duration_minutes": calculate_session_duration_minutes(merged_start, merged_end, merged_count),
        "commit_count": merged_count,
        "repos_touched": merged_repos
    }


def analyze_commit_sessions(
    commit_events: list[dict[str, Any]],
    today: str,
    now: datetime,
    previous_session_tracker: dict | None
) -> dict:
    """Compute coherent session summaries and tracker updates."""
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
            "repo": repo if isinstance(repo, str) else None
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
                "split_timeout_minutes": split_timeout
            }
    elif previous_open_session:
        previous_last = parse_iso_datetime(previous_open_session.get("last_commit"))
        previous_timeout = max(
            1,
            to_int(previous_open_session.get("split_timeout_minutes"), split_timeout)
        )
        if previous_last is not None and now - previous_last <= timedelta(minutes=previous_timeout):
            open_session = previous_open_session

    session_tracker = normalize_session_tracker({
        "open_session": open_session,
        "last_timeout_minutes": split_timeout
    })

    return {
        "session_split_timeout_minutes": split_timeout,
        "session_count_detected": len(summaries),
        "primary_session": primary_session,
        "detected_sessions": summaries[-MAX_DETECTED_SESSIONS:],
        "session_duration_minutes": to_int((primary_session or {}).get("duration_minutes"), 0),
        "session_duration_today_minutes": to_int((today_primary_session or {}).get("duration_minutes"), 0),
        "marathon_detected": marathon_detected,
        "session_tracker": session_tracker
    }


def load_previous_state(state_file: Path) -> dict | None:
    """Load previous state from state.json if it exists."""
    if not state_file.exists():
        return None
    
    try:
        with open(state_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load previous state: {e}")
        return None


def get_watched_repos() -> list[str]:
    """
    Get list of repositories to watch.
    
    Returns list of repo names in format "owner/repo"
    """
    # Try environment variable first
    watched = os.environ.get("WATCHED_REPOS", "")
    if watched:
        return [r.strip() for r in watched.split(",") if r.strip()]
    
    # Default to current user's profile repo
    current_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if current_repo:
        username = current_repo.split("/")[0]
        return [f"{username}/{username}"]
    
    return []


def detect_activity(
    watched_repos: list[str],
    last_check: datetime,
    previous_session_tracker: dict | None = None,
    now: datetime | None = None
) -> dict:
    """
    Detect activity in watched repositories.
    
    Scans all branches in each repository (limited to 5 most recently updated
    per repo to avoid API rate limits).
    
    Returns activity data including commits, repos touched, session info.
    """
    now = now or get_current_time()
    today = now.strftime("%Y-%m-%d")
    commit_events: list[dict[str, Any]] = []
    seen_commits = set()
    branches_checked = 0

    # Full implementation with PyGithub when available.
    token = os.environ.get("GH_TOKEN")
    if not HAS_GITHUB:
        print("Activity detection requires PyGithub: pip install PyGithub")
    elif not token:
        print("Warning: GH_TOKEN not set")
    else:
        g = Github(token)
        username = os.environ.get("GITHUB_REPOSITORY", "").split("/")[0]

        for repo_name in watched_repos:
            try:
                repo = g.get_repo(repo_name)

                # Get all branches and sort by most recent commit (descending)
                # Limit to 5 most recently updated branches to avoid API rate limits
                all_branches = list(repo.get_branches())
                branches = sorted(
                    all_branches,
                    key=lambda b: b.commit.commit.author.date,
                    reverse=True
                )[:5]

                print(f"  Checking {repo_name}: {len(branches)} branches (of {len(all_branches)} total)")

                for branch in branches:
                    try:
                        commits = repo.get_commits(sha=branch.name, since=last_check, author=username)

                        for commit in commits:
                            commit_sha = getattr(commit, "sha", None)
                            dedupe_key = f"{repo_name}:{commit_sha}" if commit_sha else None
                            if dedupe_key and dedupe_key in seen_commits:
                                continue
                            if dedupe_key:
                                seen_commits.add(dedupe_key)

                            author = commit.commit.author or commit.commit.committer
                            if author is None or author.date is None:
                                continue
                            commit_time = author.date
                            if commit_time.tzinfo is None:
                                commit_time = commit_time.replace(tzinfo=timezone.utc)

                            commit_events.append({
                                "timestamp": commit_time.astimezone(timezone.utc),
                                "repo": repo_name
                            })

                        branches_checked += 1

                    except Exception as e:
                        print(f"    Error checking branch {branch.name}: {e}")

            except Exception as e:
                print(f"Error checking {repo_name}: {e}")

    print(f"  Total branches checked: {branches_checked}")

    commit_events.sort(key=lambda event: event["timestamp"])
    commits_detected = len(commit_events)
    today_events = [
        event for event in commit_events
        if event["timestamp"].strftime("%Y-%m-%d") == today
    ]
    commits_today_detected = len(today_events)
    repos_touched = sorted({event.get("repo") for event in commit_events if isinstance(event.get("repo"), str)})
    repos_touched_today = sorted({event.get("repo") for event in today_events if isinstance(event.get("repo"), str)})
    last_commit_time = commit_events[-1]["timestamp"] if commit_events else None

    session_analysis = analyze_commit_sessions(
        commit_events=commit_events,
        today=today,
        now=now,
        previous_session_tracker=previous_session_tracker,
    )
    if session_analysis["marathon_detected"]:
        print(
            f"  Marathon session detected: "
            f"{session_analysis['session_duration_minutes']} minutes (primary session)"
        )

    return {
        "commits_detected": commits_detected,
        "commits_today_detected": commits_today_detected,
        "repos_touched": repos_touched,
        "repos_touched_today": repos_touched_today,
        "session_duration_minutes": session_analysis["session_duration_minutes"],
        "session_duration_today_minutes": session_analysis["session_duration_today_minutes"],
        "marathon_detected": session_analysis["marathon_detected"],
        "session_split_timeout_minutes": session_analysis["session_split_timeout_minutes"],
        "session_count_detected": session_analysis["session_count_detected"],
        "primary_session": session_analysis["primary_session"],
        "detected_sessions": session_analysis["detected_sessions"],
        "session_tracker": session_analysis["session_tracker"],
        "last_commit_timestamp": to_iso8601(last_commit_time),
        "social_events": {
            "stars_received": 0,  # TODO: Query from API
            "prs_merged": 0,
            "followers_gained": 0
        }
    }


def calculate_mood(pet: dict, github_stats: dict, repos_touched: list) -> str:
    """
    Calculate pet mood based on current stats.
    
    Mood affects the visual appearance of the pet.
    """
    stats = pet["stats"]
    
    if stats["hunger"] < 20:
        return "starving"
    elif stats["energy"] < 30:
        return "exhausted"
    elif stats["happiness"] > 80 and github_stats.get("current_streak", 0) > 3:
        return "ecstatic"
    elif len(repos_touched) > 5:
        return "scattered"
    else:
        return "content"


def calculate_stage(active_days: int) -> str:
    """
    Calculate evolution stage based on days of activity.

    Stages: baby -> teen -> adult -> elder
    Evolution is based on cumulative days with activity detected,
    not necessarily consecutive days.
    """
    if active_days < 10:
        return "baby"
    elif active_days < 50:
        return "teen"
    elif active_days < 200:
        return "adult"
    else:
        return "elder"


def apply_decay(pet: dict, hours_passed: float, activity: dict) -> dict:
    """
    Apply stat decay or recovery based on time passed and activity.
    
    Decay rates:
    - Hunger: -5 per 6 hours
    - Energy: +10 per 2 hours of rest (recovery during inactivity)
            -10 per 2 hours if still active (marathon mode)
    - Happiness: -2 per day
    """
    stats = pet["stats"]
    
    # Apply hunger decay (always decays)
    hunger_decay = 5 * hours_passed / 6
    stats["hunger"] = max(0, min(100, stats["hunger"] - hunger_decay))
    
    # Apply happiness decay (always decays slowly)
    happiness_decay = 2 * hours_passed / 24
    stats["happiness"] = max(0, min(100, stats["happiness"] - happiness_decay))
    
    # Energy: recover during rest, drain during marathons
    if activity["marathon_detected"]:
        # Marathon mode: drain energy faster
        energy_change = -(10 * hours_passed / 2)
        print(f"    Energy drain (marathon): {energy_change:.1f}")
    elif activity["commits_detected"] > 0:
        # Active but not marathon: slight energy drain
        energy_change = -(5 * hours_passed / 2)
        print(f"    Energy drain (active): {energy_change:.1f}")
    else:
        # Rest mode: recover energy
        energy_change = 10 * hours_passed / 2
        print(f"    Energy recovery (rest): +{energy_change:.1f}")
    
    stats["energy"] = max(0, min(100, stats["energy"] + energy_change))
    
    return pet


def apply_activity_bonuses(pet: dict, activity: dict) -> dict:
    """
    Apply stat bonuses from detected activity.
    
    Also applies energy penalties for marathon sessions.
    """
    stats = pet["stats"]
    commits = activity["commits_detected"]
    repos = activity["repos_touched"]
    
    if commits > 0:
        # Hunger increases (pet gets hungry from activity)
        stats["hunger"] = min(100, stats["hunger"] + commits * 5)
        # Happiness increases from activity
        stats["happiness"] = min(100, stats["happiness"] + len(repos) * 2)
        
        # Marathon penalty: additional energy drain
        if activity["marathon_detected"]:
            marathon_penalty = 15  # Flat penalty for marathon sessions
            stats["energy"] = max(0, stats["energy"] - marathon_penalty)
            print(f"    Marathon penalty: -{marathon_penalty} energy")
    
    return pet


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


def trim_active_days(active_days: set[str] | list[str], limit: int = RECENT_ACTIVE_DAYS_LIMIT) -> list[str]:
    """
    Keep only the most recent active day entries for state size control.

    `active_days_total` stores the all-time count to preserve stage progression.
    """
    normalized = sorted({d for d in active_days if isinstance(d, str)})
    if len(normalized) <= limit:
        return normalized
    return normalized[-limit:]


def calculate_current_streak(active_days: set[str], today: str) -> int:
    """Calculate consecutive active days ending on today."""
    if today not in active_days:
        return 0

    try:
        cursor = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return 0

    streak = 0
    while cursor.isoformat() in active_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def to_int(value: Any, default: int = 0) -> int:
    """Best-effort integer conversion with sane fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_reground_threshold(previous_state: dict | None) -> int:
    """Resolve re-grounding threshold from env, previous state, or default."""
    env_threshold = os.environ.get("REGROUND_THRESHOLD")
    if env_threshold is not None:
        return max(1, to_int(env_threshold, DEFAULT_REGROUND_THRESHOLD))

    if previous_state:
        previous_threshold = previous_state.get("regrounding", {}).get("threshold")
        return max(1, to_int(previous_threshold, DEFAULT_REGROUND_THRESHOLD))

    return DEFAULT_REGROUND_THRESHOLD


def ensure_stage_image_bootstrap(stage: str) -> None:
    """
    Ensure stage image directory exists.

    Re-grounding anchors live under `.codepet/stage_images/`.
    """
    stage_dir = Path(".codepet/stage_images")
    stage_dir.mkdir(parents=True, exist_ok=True)

    if stage == "baby" and not (stage_dir / "baby.png").exists():
        print("Warning: Missing stage anchor .codepet/stage_images/baby.png")


def build_image_tracking_state(
    previous_state: dict | None,
    current_stage: str,
    previous_stage: str | None,
    threshold: int
) -> tuple[dict, dict, dict]:
    """
    Build image tracking fields for state.json.

    These fields are runner-tracked metadata used by webhook preparation and
    cloud-agent re-grounding logic.
    """
    previous_image_state = (previous_state or {}).get("image_state", {})
    previous_regrounding = (previous_state or {}).get("regrounding", {})

    stage_changed = previous_stage is not None and previous_stage != current_stage
    ensure_stage_image_bootstrap(current_stage)
    if previous_stage:
        ensure_stage_image_bootstrap(previous_stage)

    if stage_changed:
        base_reference = f".codepet/stage_images/{previous_stage}.png"
        target_reference = f".codepet/stage_images/{current_stage}.png"
        current_stage_reference = base_reference
        evolution = {
            "just_occurred": True,
            "previous_stage": previous_stage,
            "new_stage": current_stage,
            "base_reference": base_reference,
            "target_reference": target_reference
        }
    else:
        current_stage_reference = f".codepet/stage_images/{current_stage}.png"
        previous_reference = previous_image_state.get("current_stage_reference")
        if previous_reference and Path(current_stage_reference).exists() is False:
            # Migration fallback: keep prior reference only if canonical anchor
            # is not yet available.
            current_stage_reference = previous_reference

        evolution = {
            "just_occurred": False,
            "previous_stage": None,
            "new_stage": None,
            "base_reference": None,
            "target_reference": None
        }

    image_state = {
        "edit_count_since_reset": max(0, to_int(previous_image_state.get("edit_count_since_reset"), 0)),
        "total_edits_all_time": max(0, to_int(previous_image_state.get("total_edits_all_time"), 0)),
        "last_reset_at": previous_image_state.get("last_reset_at"),
        "reset_count": max(0, to_int(previous_image_state.get("reset_count"), 0)),
        "current_stage_reference": current_stage_reference
    }

    should_reground = bool(previous_regrounding.get("should_reground", False))
    reason = previous_regrounding.get("reason")

    if image_state["edit_count_since_reset"] >= threshold:
        should_reground = True
        if reason is None:
            reason = "edit_threshold_reached"
    elif reason == "edit_threshold_reached":
        should_reground = False
        reason = None

    regrounding = {
        "should_reground": should_reground,
        "reason": reason,
        "threshold": threshold
    }

    return image_state, regrounding, evolution


def calculate_state(previous_state: dict | None, activity: dict, hours_passed: float) -> dict:
    """
    Calculate new pet state based on previous state, activity, and time passed.
    """
    now = get_current_time()
    today = get_today_date()
    reground_threshold = get_reground_threshold(previous_state)

    if previous_state:
        # Update existing pet
        pet = previous_state.get("pet", {})
        github_stats = previous_state.get("github", {})
        previous_stage = previous_state.get("pet", {}).get("stage")
        commits_detected_today = max(
            0,
            to_int(activity.get("commits_today_detected"), to_int(activity.get("commits_detected"), 0))
        )
        session_duration_today = max(
            0,
            to_int(
                activity.get("session_duration_today_minutes"),
                to_int(activity.get("session_duration_minutes"), 0)
            )
        )
        repos_touched_today = activity.get("repos_touched_today")
        if not isinstance(repos_touched_today, list):
            repos_touched_today = activity.get("repos_touched", []) if commits_detected_today > 0 else []

        # Reset daily counters at UTC day rollover.
        previous_update = parse_iso_datetime(previous_state.get("last_updated"))
        previous_day = previous_update.strftime("%Y-%m-%d") if previous_update else None
        if previous_day != today:
            github_stats["commits_today"] = 0
            github_stats["longest_session_today_minutes"] = 0
            github_stats["repos_touched_today"] = []

        # Ensure stats exist
        if "stats" not in pet:
            pet["stats"] = DEFAULT_PET_STATS.copy()

        # Track active days (unique dates with activity).
        # Prefer new key; fall back to legacy `active_days` for migration.
        existing_recent_days = github_stats.get("recent_active_days", github_stats.get("active_days", []))
        active_days_set = set(existing_recent_days)
        active_days_total = max(
            to_int(github_stats.get("active_days_total"), len(active_days_set)),
            len(active_days_set)
        )
        if commits_detected_today > 0 and today not in active_days_set:
            active_days_total += 1
        if commits_detected_today > 0:
            active_days_set.add(today)
        github_stats["recent_active_days"] = trim_active_days(active_days_set)
        github_stats.pop("active_days", None)
        github_stats["active_days_total"] = active_days_total
        active_days_count = active_days_total

        # Apply decay
        pet = apply_decay(pet, hours_passed, activity)

        # Apply activity bonuses
        pet = apply_activity_bonuses(pet, activity)

        # Update GitHub stats
        github_stats["commits_today"] = max(0, to_int(github_stats.get("commits_today"), 0)) + commits_detected_today
        github_stats["total_commits_all_time"] = max(
            0,
            to_int(github_stats.get("total_commits_all_time"), 0)
        ) + max(0, to_int(activity.get("commits_detected"), 0))
        github_stats["longest_session_today_minutes"] = max(
            max(0, to_int(github_stats.get("longest_session_today_minutes"), 0)),
            session_duration_today
        )
        github_stats["session_tracker"] = normalize_session_tracker(
            activity.get("session_tracker", github_stats.get("session_tracker"))
        )
        github_stats["current_streak"] = calculate_current_streak(set(github_stats["recent_active_days"]), today)
        if activity.get("last_commit_timestamp"):
            github_stats["last_commit_timestamp"] = activity["last_commit_timestamp"]
        elif github_stats.get("last_commit_timestamp") is None:
            # Migration fallback: older state files may be missing this field.
            # Preserve a stable reference so back-off can grow over time.
            if github_stats.get("total_commits_all_time", 0) > 0:
                github_stats["last_commit_timestamp"] = previous_state.get("last_updated")
            else:
                github_stats["last_commit_timestamp"] = None
        if repos_touched_today:
            github_stats["repos_touched_today"] = sorted(set(
                github_stats.get("repos_touched_today", []) + repos_touched_today
            ))
        elif "repos_touched_today" not in github_stats:
            github_stats["repos_touched_today"] = []

        # Calculate mood and stage
        pet["mood"] = calculate_mood(pet, github_stats, activity["repos_touched"])
        pet["stage"] = calculate_stage(active_days_count)

    else:
        # Initial state for new pet - starts as baby, not egg
        commits_detected_today = max(
            0,
            to_int(activity.get("commits_today_detected"), to_int(activity.get("commits_detected"), 0))
        )
        session_duration_today = max(
            0,
            to_int(
                activity.get("session_duration_today_minutes"),
                to_int(activity.get("session_duration_minutes"), 0)
            )
        )
        repos_touched_today = activity.get("repos_touched_today")
        if not isinstance(repos_touched_today, list):
            repos_touched_today = activity.get("repos_touched", []) if commits_detected_today > 0 else []

        active_days_set = set()
        if commits_detected_today > 0:
            active_days_set.add(today)

        pet = {
            "name": "Byte",
            "stage": "baby",
            "stats": DEFAULT_PET_STATS.copy(),
            "mood": "content",
            "derived_state": {
                "is_sleeping": False,
                "is_ghost": False,
                "days_inactive": 0
            }
        }
        github_stats = {
            "current_streak": calculate_current_streak(active_days_set, today),
            "commits_today": commits_detected_today,
            "longest_session_today_minutes": session_duration_today,
            "repos_touched_today": sorted(set(repos_touched_today)),
            "last_commit_timestamp": activity.get("last_commit_timestamp"),
            "total_commits_all_time": activity["commits_detected"],
            "recent_active_days": trim_active_days(active_days_set),
            "active_days_total": len(active_days_set),
            "session_tracker": normalize_session_tracker(activity.get("session_tracker"))
        }
        previous_stage = None

    image_state, regrounding, evolution = build_image_tracking_state(
        previous_state=previous_state,
        current_stage=pet["stage"],
        previous_stage=previous_stage,
        threshold=reground_threshold
    )

    return {
        "last_updated": now.isoformat(),
        "updated_by": "github-actions-runner",
        "pet": pet,
        "github": github_stats,
        "image_state": image_state,
        "regrounding": regrounding,
        "evolution": evolution,
        # Compatibility helper for consumers expecting a flat boolean flag.
        "evolution_just_occurred": evolution["just_occurred"]
    }


def write_json_file(path: Path, data: dict) -> None:
    """Write data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main() -> int:
    """Main entry point."""
    print("=" * 50)
    print("CodePet State Calculator")
    print("=" * 50)
    
    now = get_current_time()
    
    # Setup paths
    activity_file = Path(".codepet/activity.json")
    state_file = Path(".codepet/state.json")
    
    # Load previous state
    previous_state = load_previous_state(state_file)
    
    # Calculate time window
    if previous_state:
        last_check = datetime.fromisoformat(previous_state["last_updated"].replace("Z", "+00:00"))
        hours_passed = (now - last_check).total_seconds() / 3600
    else:
        last_check = now
        hours_passed = 0
    
    print(f"\nTime window: {last_check.isoformat()} to {now.isoformat()}")
    print(f"Hours since last check: {hours_passed:.2f}")
    
    # Get watched repos
    watched_repos = get_watched_repos()
    print(f"\nWatching {len(watched_repos)} repositories:")
    for repo in watched_repos:
        print(f"  - {repo}")
    
    # Detect activity
    print("\nDetecting activity...")
    previous_session_tracker = None
    if previous_state:
        previous_session_tracker = previous_state.get("github", {}).get("session_tracker")

    activity = detect_activity(
        watched_repos=watched_repos,
        last_check=last_check,
        previous_session_tracker=previous_session_tracker,
        now=now
    )
    print(f"  Commits detected: {activity['commits_detected']}")
    print(f"  Repos touched: {activity['repos_touched']}")
    
    # Build activity.json
    activity_data = {
        "timestamp": now.isoformat(),
        "period": {
            "start": last_check.isoformat(),
            "end": now.isoformat()
        },
        "activity": activity,
        "calculation": {
            "previous_check": last_check.isoformat(),
            "hours_since_last_check": round(hours_passed, 2)
        }
    }
    
    # Calculate new state
    print("\nCalculating pet state...")
    new_state = calculate_state(previous_state, activity, hours_passed)
    
    # Print state summary
    pet = new_state["pet"]
    github_stats = new_state["github"]
    active_days_total = to_int(
        github_stats.get("active_days_total"),
        len(github_stats.get("recent_active_days", github_stats.get("active_days", [])))
    )
    print(f"  Name: {pet['name']}")
    print(f"  Stage: {pet['stage']}")
    print(f"  Mood: {pet['mood']}")
    print(f"  Active days: {active_days_total}")
    print(f"  Stats: hunger={pet['stats']['hunger']:.1f}, "
          f"energy={pet['stats']['energy']:.1f}, "
          f"happiness={pet['stats']['happiness']:.1f}")
    
    # Write files
    print(f"\nWriting {activity_file}...")
    write_json_file(activity_file, activity_data)
    
    print(f"Writing {state_file}...")
    write_json_file(state_file, new_state)
    
    # Output for GitHub Actions
    print("\nOutputs:")
    print(f"  commits_detected={activity['commits_detected']}")
    print(f"  mood={pet['mood']}")
    print(f"  stage={pet['stage']}")
    
    # Determine if webhook should trigger
    should_trigger = activity["commits_detected"] > 0 or hours_passed > 2
    print(f"  should_trigger={str(should_trigger).lower()}")
    
    print("\n" + "=" * 50)
    print("State calculation complete!")
    print("=" * 50)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
