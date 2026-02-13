#!/usr/bin/env python3
"""
CodePet Back-off Logic Calculator

Determines whether to trigger the Kilo webhook based on time since last activity.
Implements progressive back-off to avoid wasting Kilo credits during inactivity.

Outputs GitHub Actions variables via GITHUB_OUTPUT environment file.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc.output_utils import set_output as _set_output


def set_output(key: str, value: str) -> None:
    """Compatibility wrapper around the shared output helper."""
    _set_output(key, value)


def parse_iso8601(timestamp: str) -> datetime:
    """Parse ISO8601 timestamp and normalize to UTC."""
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def read_run_window(activity_file: Path) -> tuple[datetime, datetime | None]:
    """
    Read current and previous scheduler check timestamps from activity.json.

    Returns:
        (current_check, previous_check_or_none)
    """
    fallback_now = datetime.now(timezone.utc)

    if not activity_file.exists():
        return fallback_now, None

    try:
        with open(activity_file) as f:
            activity = json.load(f)

        current_check_str = activity.get("timestamp")
        previous_check_str = activity.get("calculation", {}).get("previous_check")

        current_check = parse_iso8601(current_check_str) if current_check_str else fallback_now
        previous_check = parse_iso8601(previous_check_str) if previous_check_str else None
        return current_check, previous_check

    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing run window from activity file: {e}")
        return fallback_now, None


def read_last_activity(state_file: Path, activity_file: Path) -> datetime | None:
    """
    Read the last commit timestamp from state/activity files.

    Priority:
    1) state.json -> github.last_commit_timestamp (persistent across no-commit runs)
    2) activity.json -> current window when commits_detected > 0 (best effort)
    """
    try:
        if state_file.exists():
            with open(state_file) as f:
                state = json.load(f)

            last_commit_str = state.get("github", {}).get("last_commit_timestamp")
            if last_commit_str:
                return parse_iso8601(last_commit_str)

        if activity_file.exists():
            with open(activity_file) as f:
                activity = json.load(f)

            activity_block = activity.get("activity", {})
            if activity_block.get("commits_detected", 0) > 0:
                last_commit_str = activity_block.get("last_commit_timestamp") or activity.get("timestamp")
                if last_commit_str:
                    return parse_iso8601(last_commit_str)

    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing activity/state file: {e}")

    return None


def crossed_interval_boundary(
    last_activity: datetime,
    previous_check: datetime | None,
    current_check: datetime,
    interval_minutes: int
) -> bool:
    """
    Determine whether an interval boundary was crossed since previous check.

    This makes back-off robust to scheduler jitter: if a job starts late, the
    trigger fires on the first run after the boundary is crossed.
    """
    current_inactive_minutes = max(0.0, (current_check - last_activity).total_seconds() / 60)

    if previous_check is None:
        return current_inactive_minutes >= interval_minutes

    safe_previous_check = min(previous_check, current_check)
    previous_inactive_minutes = max(0.0, (safe_previous_check - last_activity).total_seconds() / 60)

    previous_bucket = int(previous_inactive_minutes // interval_minutes)
    current_bucket = int(current_inactive_minutes // interval_minutes)
    return current_bucket > previous_bucket


def calculate_backoff(
    hours_inactive: int,
    current_time: datetime,
    last_activity: datetime,
    previous_check: datetime | None
) -> dict:
    """
    Calculate back-off logic based on hours of inactivity.
    
    Progressive back-off strategy for an hourly scheduler:
    - < 2 hours: Active user, trigger every run (hourly)
    - 2-4 hours: Back off to 2 hour intervals
    - 4-8 hours: Back off to 4 hour intervals
    - 8+ hours: Back off to 6 hour intervals (max)
    
    Returns:
        Dict with should_trigger, reason, next_interval, hours_inactive
    """
    if hours_inactive < 2:
        # Active: trigger on every scheduled run (hourly cron)
        return {
            "should_trigger": True,
            "reason": "active_user",
            "next_interval": 60,
            "hours_inactive": hours_inactive
        }
    
    elif hours_inactive < 4:
        should_trigger = crossed_interval_boundary(last_activity, previous_check, current_time, 120)
        return {
            "should_trigger": should_trigger,
            "reason": "backoff_2hr" if should_trigger else "skipping_for_backoff",
            "next_interval": 120,
            "hours_inactive": hours_inactive
        }
    
    elif hours_inactive < 8:
        should_trigger = crossed_interval_boundary(last_activity, previous_check, current_time, 240)
        return {
            "should_trigger": should_trigger,
            "reason": "backoff_4hr" if should_trigger else "skipping_for_backoff",
            "next_interval": 240,
            "hours_inactive": hours_inactive
        }
    
    else:
        should_trigger = crossed_interval_boundary(last_activity, previous_check, current_time, 360)
        return {
            "should_trigger": should_trigger,
            "reason": "backoff_6hr" if should_trigger else "skipping_for_backoff",
            "next_interval": 360,
            "hours_inactive": hours_inactive
        }


def main() -> int:
    """
    Main entry point.
    
    Returns:
        Exit code (0 for success, 1 for error)
    """
    print("=" * 50)
    print("CodePet Back-off Logic Calculator")
    print("=" * 50)
    
    # Setup paths
    activity_file = Path(".codepet/activity.json")
    state_file = Path(".codepet/state.json")

    # Read scheduler window and last commit activity
    current_time, previous_check = read_run_window(activity_file)
    last_activity = read_last_activity(state_file, activity_file)
    
    if last_activity is None:
        if not state_file.exists() and not activity_file.exists():
            # First run - always trigger
            result = {
                "should_trigger": True,
                "reason": "first_run",
                "next_interval": 60,
                "hours_inactive": 0
            }
        else:
            # Existing setup but no commit history tracked yet: default to max back-off.
            result = {
                "should_trigger": False,
                "reason": "skipping_for_backoff",
                "next_interval": 360,
                "hours_inactive": 8
            }
    else:
        hours_inactive = max(0, int((current_time - last_activity).total_seconds() / 3600))
        result = calculate_backoff(hours_inactive, current_time, last_activity, previous_check)
    
    # Output all results for GitHub Actions
    print("\nOutputs:")
    set_output("should_trigger", str(result["should_trigger"]).lower())
    set_output("reason", result["reason"])
    set_output("next_interval", str(result["next_interval"]))
    set_output("hours_inactive", str(result["hours_inactive"]))
    
    # Summary for logs
    print("\n" + "=" * 50)
    print("Decision Summary:")
    print(f"  Last activity: {last_activity.isoformat() if last_activity else 'None (first run)'}")
    print(f"  Hours inactive: {result['hours_inactive']}")
    print(f"  Current time: {current_time.strftime('%H:%M UTC')}")
    print(f"  Should trigger webhook: {result['should_trigger']}")
    print(f"  Reason: {result['reason']}")
    print(f"  Next interval: {result['next_interval']} minutes")
    print("=" * 50)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
