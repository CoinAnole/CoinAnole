"""State object builder for CodePet."""

from .constants import DEFAULT_PET_STATS
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
from .time_utils import get_current_time, get_today_date, parse_iso_datetime, to_int


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
            to_int(activity.get("commits_today_detected"), to_int(activity.get("commits_detected"), 0)),
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

        # Ensure stats exist
        if "stats" not in pet:
            pet["stats"] = DEFAULT_PET_STATS.copy()

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
        ) + max(0, to_int(activity.get("commits_detected"), 0))
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
        pet["mood"] = calculate_mood(pet, github_stats, activity["repos_touched"])
        pet["stage"] = calculate_stage(active_days_count)

    else:
        # Initial state for new pet - starts as baby, not egg
        commits_detected_today = max(
            0,
            to_int(activity.get("commits_today_detected"), to_int(activity.get("commits_detected"), 0)),
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
            "total_commits_all_time": activity["commits_detected"],
            "recent_active_days": trim_active_days(active_days_set),
            "active_days_total": len(active_days_set),
            "session_tracker": normalize_session_tracker(activity.get("session_tracker")),
        }
        previous_stage = None

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
        "image_state": image_state,
        "regrounding": regrounding,
        "evolution": evolution,
        # Compatibility helper for consumers expecting a flat boolean flag.
        "evolution_just_occurred": evolution["just_occurred"],
    }
