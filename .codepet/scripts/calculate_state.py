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

import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc.activity_detection import HAS_GITHUB, detect_activity, get_watched_repos
from state_calc.constants import (
    DEFAULT_PET_STATS,
    DEFAULT_REGROUND_THRESHOLD,
    DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES,
    MARATHON_MIN_COMMITS,
    MARATHON_THRESHOLD_MINUTES,
    MAX_DETECTED_SESSIONS,
    RECENT_ACTIVE_DAYS_LIMIT,
    SESSION_SPLIT_TIMEOUT_MINUTES_MAX,
    SESSION_SPLIT_TIMEOUT_MINUTES_MIN,
)
from state_calc.image_tracking import (
    build_image_tracking_state,
    ensure_stage_image_bootstrap,
    get_reground_threshold,
)
from state_calc.io_utils import load_previous_state, write_json_file
from state_calc.pet_rules import (
    apply_activity_bonuses,
    apply_decay,
    calculate_current_streak,
    calculate_mood,
    calculate_stage,
    trim_active_days,
)
from state_calc.session_analysis import (
    analyze_commit_sessions,
    calculate_session_duration_minutes,
    compute_adaptive_timeout,
    merge_open_session_into_summary,
    merge_with_open_session,
    normalize_open_session,
    normalize_session_tracker,
    select_primary_session,
    split_into_sessions,
    summarize_session,
)
from state_calc.state_builder import calculate_state
from state_calc.time_utils import (
    get_current_time,
    get_today_date,
    parse_iso_datetime,
    to_int,
    to_iso8601,
)


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
        now=now,
    )
    print(f"  Commits detected: {activity['commits_detected']}")
    print(f"  Repos touched: {activity['repos_touched']}")

    # Build activity.json
    activity_data = {
        "timestamp": now.isoformat(),
        "period": {
            "start": last_check.isoformat(),
            "end": now.isoformat(),
        },
        "activity": activity,
        "calculation": {
            "previous_check": last_check.isoformat(),
            "hours_since_last_check": round(hours_passed, 2),
        },
    }

    # Calculate new state
    print("\nCalculating pet state...")
    new_state = calculate_state(previous_state, activity, hours_passed)

    # Print state summary
    pet = new_state["pet"]
    github_stats = new_state["github"]
    active_days_total = to_int(
        github_stats.get("active_days_total"),
        len(github_stats.get("recent_active_days", github_stats.get("active_days", []))),
    )
    print(f"  Name: {pet['name']}")
    print(f"  Stage: {pet['stage']}")
    print(f"  Mood: {pet['mood']}")
    print(f"  Active days: {active_days_total}")
    print(
        f"  Stats: hunger={pet['stats']['hunger']:.1f}, "
        f"energy={pet['stats']['energy']:.1f}, "
        f"happiness={pet['stats']['happiness']:.1f}"
    )

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


__all__ = [
    "HAS_GITHUB",
    "DEFAULT_PET_STATS",
    "DEFAULT_REGROUND_THRESHOLD",
    "RECENT_ACTIVE_DAYS_LIMIT",
    "DEFAULT_SESSION_SPLIT_TIMEOUT_MINUTES",
    "SESSION_SPLIT_TIMEOUT_MINUTES_MIN",
    "SESSION_SPLIT_TIMEOUT_MINUTES_MAX",
    "MARATHON_THRESHOLD_MINUTES",
    "MARATHON_MIN_COMMITS",
    "MAX_DETECTED_SESSIONS",
    "to_iso8601",
    "get_current_time",
    "calculate_session_duration_minutes",
    "compute_adaptive_timeout",
    "split_into_sessions",
    "summarize_session",
    "select_primary_session",
    "merge_with_open_session",
    "normalize_open_session",
    "normalize_session_tracker",
    "merge_open_session_into_summary",
    "analyze_commit_sessions",
    "load_previous_state",
    "get_watched_repos",
    "detect_activity",
    "calculate_mood",
    "calculate_stage",
    "apply_decay",
    "apply_activity_bonuses",
    "get_today_date",
    "parse_iso_datetime",
    "trim_active_days",
    "calculate_current_streak",
    "to_int",
    "get_reground_threshold",
    "ensure_stage_image_bootstrap",
    "build_image_tracking_state",
    "calculate_state",
    "write_json_file",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
