"""State object builder for CodePet."""

import copy
import math

from .constants import (
    DEFAULT_PET_STATS,
    LATE_NIGHT_END,
    LATE_NIGHT_START,
    QUIET_HOURS_END,
    QUIET_HOURS_START,
    SLEEP_MIN_INACTIVE_HOURS,
)
from .image_tracking import build_image_tracking_state, get_reground_threshold
from .pet_rules import (
    apply_activity_bonuses,
    apply_decay,
    calculate_current_streak,
    calculate_mood,
    calculate_stage,
    trim_active_days,
)
from .session_analysis import normalize_session_tracker
from .time_utils import (
    classify_time_of_day,
    get_current_time,
    get_timezone_name,
    get_today_date,
    interval_overlaps_local_window,
    is_hour_in_window,
    parse_iso_datetime,
    to_int,
    to_local_time,
)

VALID_TIME_OF_DAY = {"morning", "afternoon", "evening", "night"}


def _resolve_previous_time_of_day(previous_state: dict | None, timezone_name: str) -> str | None:
    """Read previous time-of-day bucket for transition detection."""
    if not isinstance(previous_state, dict):
        return None

    temporal = previous_state.get("temporal")
    if isinstance(temporal, dict):
        previous_time_of_day = temporal.get("time_of_day")
        if previous_time_of_day in VALID_TIME_OF_DAY:
            return previous_time_of_day

    previous_update = parse_iso_datetime(previous_state.get("last_updated"))
    if previous_update is None:
        return None
    return classify_time_of_day(to_local_time(previous_update, timezone_name).hour)


def calculate_state(previous_state: dict | None, activity: dict, hours_passed: float) -> dict:
    """
    Calculate new pet state based on previous state, activity, and time passed.
    """
    now = get_current_time()
    today = get_today_date()
    timezone_name = get_timezone_name()
    commits_detected = max(0, to_int(activity.get("commits_detected"), 0))
    reground_threshold = get_reground_threshold(previous_state)

    if previous_state:
        # Update existing pet
        pet = copy.deepcopy(previous_state.get("pet", {}))
        github_stats = copy.deepcopy(previous_state.get("github", {}))
        previous_stage = previous_state.get("pet", {}).get("stage")
        commits_detected_today = max(
            0,
            to_int(activity.get("commits_today_detected"), commits_detected),
        )
        session_duration_today = max(
            0,
            to_int(
                activity.get("session_duration_today_minutes"),
                to_int(activity.get("session_duration_minutes"), 0),
            ),
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

        # Ensure stats exist and migrate legacy key `hunger` -> `satiety`.
        if "stats" not in pet or not isinstance(pet["stats"], dict):
            pet["stats"] = DEFAULT_PET_STATS.copy()
        else:
            stats = pet["stats"]
            if "satiety" not in stats and "hunger" in stats:
                stats["satiety"] = stats["hunger"]
            stats.pop("hunger", None)
            for stat_name, default_value in DEFAULT_PET_STATS.items():
                if stat_name not in stats:
                    stats[stat_name] = default_value

        # Track active days (unique dates with activity).
        # Prefer new key; fall back to legacy `active_days` for migration.
        existing_recent_days = github_stats.get("recent_active_days", github_stats.get("active_days", []))
        active_days_set = set(existing_recent_days)
        active_days_total = max(
            to_int(github_stats.get("active_days_total"), len(active_days_set)),
            len(active_days_set),
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
            to_int(github_stats.get("total_commits_all_time"), 0),
        ) + commits_detected
        github_stats["longest_session_today_minutes"] = max(
            max(0, to_int(github_stats.get("longest_session_today_minutes"), 0)),
            session_duration_today,
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
        pet["mood"] = calculate_mood(pet, github_stats, activity.get("repos_touched", []))
        pet["stage"] = calculate_stage(active_days_count)

    else:
        # Initial state for new pet - starts as baby, not egg
        commits_detected_today = max(
            0,
            to_int(activity.get("commits_today_detected"), commits_detected),
        )
        session_duration_today = max(
            0,
            to_int(
                activity.get("session_duration_today_minutes"),
                to_int(activity.get("session_duration_minutes"), 0),
            ),
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
                "days_inactive": 0,
            },
        }
        github_stats = {
            "current_streak": calculate_current_streak(active_days_set, today),
            "commits_today": commits_detected_today,
            "longest_session_today_minutes": session_duration_today,
            "repos_touched_today": sorted(set(repos_touched_today)),
            "last_commit_timestamp": activity.get("last_commit_timestamp"),
            "total_commits_all_time": commits_detected,
            "recent_active_days": trim_active_days(active_days_set),
            "active_days_total": len(active_days_set),
            "session_tracker": normalize_session_tracker(activity.get("session_tracker")),
        }
        previous_stage = None

    if "derived_state" not in pet or not isinstance(pet["derived_state"], dict):
        pet["derived_state"] = {"is_sleeping": False, "is_ghost": False, "days_inactive": 0}
    derived_state = pet["derived_state"]
    derived_state["is_ghost"] = bool(derived_state.get("is_ghost", False))

    local_now = to_local_time(now, timezone_name)
    local_hour = local_now.hour
    time_of_day = classify_time_of_day(local_hour)
    previous_time_of_day = _resolve_previous_time_of_day(previous_state, timezone_name)
    time_of_day_transition = (
        f"{previous_time_of_day}_to_{time_of_day}"
        if previous_time_of_day and previous_time_of_day != time_of_day
        else "none"
    )

    last_commit_time = parse_iso_datetime(github_stats.get("last_commit_timestamp"))
    hours_since_last_commit = None
    if last_commit_time is not None:
        hours_since_last_commit = max(0.0, (now - last_commit_time).total_seconds() / 3600)

    is_quiet_hours = is_hour_in_window(local_hour, QUIET_HOURS_START, QUIET_HOURS_END)
    is_late_night_coding = bool(
        commits_detected > 0 and is_hour_in_window(local_hour, LATE_NIGHT_START, LATE_NIGHT_END)
    )
    inactive_overnight = bool(
        commits_detected == 0
        and last_commit_time is not None
        and interval_overlaps_local_window(
            start_utc=last_commit_time,
            end_utc=now,
            timezone_name=timezone_name,
            window_start_hour=0,
            window_end_hour=6,
        )
    )
    has_meaningful_inactivity = bool(
        inactive_overnight
        or (
            hours_since_last_commit is not None
            and hours_since_last_commit >= SLEEP_MIN_INACTIVE_HOURS
        )
    )
    derived_state["is_sleeping"] = bool(
        is_quiet_hours
        and commits_detected == 0
        and not is_late_night_coding
        and has_meaningful_inactivity
    )
    derived_state["days_inactive"] = (
        max(0, math.floor(hours_since_last_commit / 24)) if hours_since_last_commit is not None else 0
    )

    temporal = {
        "timezone": timezone_name,
        "local_timestamp": local_now.isoformat(),
        "local_date": local_now.strftime("%Y-%m-%d"),
        "local_hour": local_hour,
        "time_of_day": time_of_day,
        "time_of_day_transition": time_of_day_transition,
        "hours_since_last_commit": (
            round(hours_since_last_commit, 2) if hours_since_last_commit is not None else None
        ),
        "is_quiet_hours": is_quiet_hours,
        "is_late_night_coding": is_late_night_coding,
        "inactive_overnight": inactive_overnight,
    }

    image_state, regrounding, evolution = build_image_tracking_state(
        previous_state=previous_state,
        current_stage=pet["stage"],
        previous_stage=previous_stage,
        threshold=reground_threshold,
    )

    return {
        "last_updated": now.isoformat(),
        "updated_by": "github-actions-runner",
        "pet": pet,
        "github": github_stats,
        "temporal": temporal,
        "image_state": image_state,
        "regrounding": regrounding,
        "evolution": evolution,
        # Compatibility helper for consumers expecting a flat boolean flag.
        "evolution_just_occurred": evolution["just_occurred"],
    }
