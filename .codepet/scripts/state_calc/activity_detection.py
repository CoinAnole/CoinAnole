"""GitHub activity detection and repository selection."""

import os
from datetime import datetime, timezone
from typing import Any

from .session_analysis import analyze_commit_sessions
from .time_utils import get_current_time, to_iso8601

# Optional import - only needed if PyGithub is available
try:
    from github import Github

    HAS_GITHUB = True
except ImportError:
    HAS_GITHUB = False
    print("Warning: PyGithub not installed, activity detection will be limited")


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
    now: datetime | None = None,
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
                    reverse=True,
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
                                "repo": repo_name,
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
            "followers_gained": 0,
        },
    }
