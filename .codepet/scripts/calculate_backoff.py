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


def set_output(key: str, value: str) -> None:
    """
    Write output for GitHub Actions or print for local testing.
    
    In GitHub Actions, writes to GITHUB_OUTPUT file.
    Locally, just prints to stdout.
    """
    output_file = os.environ.get("GITHUB_OUTPUT")
    
    if output_file:
        # Running in GitHub Actions
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        # Running locally - print for visibility
        print(f"::set-output name={key}::{value}")
    
    # Always print for logs
    print(f"  {key}={value}")


def parse_iso8601(timestamp: str) -> datetime:
    """Parse ISO8601 timestamp and normalize to UTC."""
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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


def calculate_backoff(hours_inactive: int, current_time: datetime) -> dict:
    """
    Calculate back-off logic based on hours of inactivity.
    
    Progressive back-off strategy:
    - < 2 hours: Active user, trigger every 30 min (normal)
    - 2-4 hours: Back off to 1 hour intervals
    - 4-8 hours: Back off to 2 hour intervals  
    - 8+ hours: Back off to 6 hour intervals (max)
    
    Returns:
        Dict with should_trigger, reason, next_interval, hours_inactive
    """
    current_hour = current_time.hour
    current_min = current_time.minute
    
    if hours_inactive < 2:
        # Active: trigger every 30 min
        return {
            "should_trigger": True,
            "reason": "active_user",
            "next_interval": 30,
            "hours_inactive": hours_inactive
        }
    
    elif hours_inactive < 4:
        # 2-4 hours: back off to 1 hour
        # Trigger at minute 00 (skip :30 runs)
        if current_min < 30:
            return {
                "should_trigger": True,
                "reason": "backoff_1hr",
                "next_interval": 60,
                "hours_inactive": hours_inactive
            }
        else:
            return {
                "should_trigger": False,
                "reason": "skipping_for_backoff",
                "next_interval": 60,
                "hours_inactive": hours_inactive
            }
    
    elif hours_inactive < 8:
        # 4-8 hours: back off to 2 hours
        # Trigger only at even hours (00, 02, 04...) at minute 00
        if (current_hour % 2 == 0) and current_min < 30:
            return {
                "should_trigger": True,
                "reason": "backoff_2hr",
                "next_interval": 120,
                "hours_inactive": hours_inactive
            }
        else:
            return {
                "should_trigger": False,
                "reason": "skipping_for_backoff",
                "next_interval": 120,
                "hours_inactive": hours_inactive
            }
    
    else:
        # 8+ hours: back off to 6 hours max
        # Trigger at 00, 06, 12, 18 at minute 00
        if current_hour in [0, 6, 12, 18] and current_min < 30:
            return {
                "should_trigger": True,
                "reason": "backoff_6hr",
                "next_interval": 360,
                "hours_inactive": hours_inactive
            }
        else:
            return {
                "should_trigger": False,
                "reason": "skipping_for_backoff",
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

    # Read last commit activity
    last_activity = read_last_activity(state_file, activity_file)
    
    # Determine back-off logic
    current_time = datetime.now(timezone.utc)
    
    if last_activity is None:
        if not state_file.exists() and not activity_file.exists():
            # First run - always trigger
            result = {
                "should_trigger": True,
                "reason": "first_run",
                "next_interval": 30,
                "hours_inactive": 0
            }
        else:
            # Existing setup but no commit history tracked yet: default to max back-off.
            result = calculate_backoff(8, current_time)
    else:
        hours_inactive = max(0, int((current_time - last_activity).total_seconds() / 3600))
        result = calculate_backoff(hours_inactive, current_time)
    
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
