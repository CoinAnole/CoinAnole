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


def read_last_activity(activity_file: Path) -> tuple[datetime | None, int]:
    """
    Read the last activity timestamp from activity.json.
    
    Returns:
        Tuple of (last_activity datetime or None, hours_inactive)
    """
    if not activity_file.exists():
        print("No activity file found - assuming first run")
        return None, 0
    
    try:
        with open(activity_file) as f:
            activity = json.load(f)
        
        last_activity_str = activity.get("timestamp")
        if not last_activity_str:
            print("No timestamp in activity file")
            return None, 0
        
        # Parse ISO 8601 timestamp
        last_activity = datetime.fromisoformat(last_activity_str.replace("Z", "+00:00"))
        
        # Calculate hours inactive
        current_time = datetime.now(timezone.utc)
        hours_inactive = int((current_time - last_activity).total_seconds() / 3600)
        
        return last_activity, hours_inactive
        
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error parsing activity file: {e}")
        return None, 0


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
    
    # Read last activity
    last_activity, hours_inactive = read_last_activity(activity_file)
    
    # Determine back-off logic
    current_time = datetime.now(timezone.utc)
    
    if last_activity is None:
        # First run - always trigger
        result = {
            "should_trigger": True,
            "reason": "first_run",
            "next_interval": 30,
            "hours_inactive": hours_inactive
        }
    else:
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
