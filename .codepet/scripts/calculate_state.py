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
from datetime import datetime, timezone
from pathlib import Path
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


def detect_activity(watched_repos: list[str], last_check: datetime) -> dict:
    """
    Detect activity in watched repositories.
    
    Scans all branches in each repository (limited to 5 most recently updated
    per repo to avoid API rate limits).
    
    Returns activity data including commits, repos touched, session info.
    """
    # For now, simplified version without PyGithub dependency
    # In production, this would use the GitHub API
    
    if not HAS_GITHUB:
        print("Activity detection requires PyGithub: pip install PyGithub")
        return {
            "commits_detected": 0,
            "repos_touched": [],
            "session_duration_minutes": 0,
            "marathon_detected": False,
            "last_commit_timestamp": None,
            "social_events": {
                "stars_received": 0,
                "prs_merged": 0,
                "followers_gained": 0
            }
        }
    
    # Full implementation with PyGithub
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("Warning: GH_TOKEN not set")
        return {
            "commits_detected": 0,
            "repos_touched": [],
            "session_duration_minutes": 0,
            "marathon_detected": False,
            "last_commit_timestamp": None,
            "social_events": {
                "stars_received": 0,
                "prs_merged": 0,
                "followers_gained": 0
            }
        }
    
    g = Github(token)
    username = os.environ.get("GITHUB_REPOSITORY", "").split("/")[0]
    
    commits_detected = 0
    repos_touched = set()
    last_commit_time = None
    branches_checked = 0
    
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
                        commits_detected += 1
                        repos_touched.add(repo_name)
                        commit_time = commit.commit.author.date
                        
                        if last_commit_time is None or commit_time > last_commit_time:
                            last_commit_time = commit_time
                    
                    branches_checked += 1
                    
                except Exception as e:
                    print(f"    Error checking branch {branch.name}: {e}")
                    
        except Exception as e:
            print(f"Error checking {repo_name}: {e}")
    
    print(f"  Total branches checked: {branches_checked}")
    
    # Calculate session duration from commits
    session_duration = 0
    marathon = False
    
    # If we found commits, calculate session duration from first to last commit
    if commits_detected > 0 and last_commit_time:
        # We need to track first commit time too for proper session calculation
        # For now, estimate based on number of commits (assume ~10 min per commit on avg)
        session_duration = commits_detected * 10
        
        # Marathon = 2+ hour session (120+ minutes)
        marathon = session_duration >= 120
        
        if marathon:
            print(f"  Marathon session detected: {session_duration} minutes")
    
    return {
        "commits_detected": commits_detected,
        "repos_touched": list(repos_touched),
        "session_duration_minutes": session_duration,
        "marathon_detected": marathon,
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
        current_stage_reference = previous_image_state.get("current_stage_reference")
        if not current_stage_reference:
            current_stage_reference = f".codepet/stage_images/{current_stage}.png"

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

        # Ensure stats exist
        if "stats" not in pet:
            pet["stats"] = DEFAULT_PET_STATS.copy()

        # Track active days (unique dates with activity)
        active_days_set = set(github_stats.get("active_days", []))
        if activity["commits_detected"] > 0:
            active_days_set.add(today)
        github_stats["active_days"] = sorted(list(active_days_set))
        active_days_count = len(active_days_set)

        # Apply decay
        pet = apply_decay(pet, hours_passed, activity)

        # Apply activity bonuses
        pet = apply_activity_bonuses(pet, activity)

        # Update GitHub stats
        github_stats["commits_today"] = github_stats.get("commits_today", 0) + activity["commits_detected"]
        github_stats["total_commits_all_time"] = github_stats.get("total_commits_all_time", 0) + activity["commits_detected"]
        if activity.get("last_commit_timestamp"):
            github_stats["last_commit_timestamp"] = activity["last_commit_timestamp"]
        elif github_stats.get("last_commit_timestamp") is None:
            # Migration fallback: older state files may be missing this field.
            # Preserve a stable reference so back-off can grow over time.
            if github_stats.get("total_commits_all_time", 0) > 0:
                github_stats["last_commit_timestamp"] = previous_state.get("last_updated")
            else:
                github_stats["last_commit_timestamp"] = None
        if activity["repos_touched"]:
            github_stats["repos_touched_today"] = list(set(
                github_stats.get("repos_touched_today", []) + activity["repos_touched"]
            ))

        # Calculate mood and stage
        pet["mood"] = calculate_mood(pet, github_stats, activity["repos_touched"])
        pet["stage"] = calculate_stage(active_days_count)

    else:
        # Initial state for new pet - starts as baby, not egg
        active_days_set = set()
        if activity["commits_detected"] > 0:
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
            "current_streak": 0,
            "commits_today": activity["commits_detected"],
            "longest_session_today_minutes": 0,
            "repos_touched_today": activity["repos_touched"],
            "last_commit_timestamp": activity.get("last_commit_timestamp"),
            "total_commits_all_time": activity["commits_detected"],
            "active_days": sorted(list(active_days_set))
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
    activity = detect_activity(watched_repos, last_check)
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
    active_days = len(github_stats.get("active_days", []))
    print(f"  Name: {pet['name']}")
    print(f"  Stage: {pet['stage']}")
    print(f"  Mood: {pet['mood']}")
    print(f"  Active days: {active_days}")
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
