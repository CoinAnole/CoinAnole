import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc import state_builder
from state_calc.constants import DEFAULT_PET_STATS


FIXED_NOW = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)
FIXED_TODAY = "2026-02-13"


def make_activity(
    *,
    commits_detected: int,
    commits_today_detected: int,
    repos_touched: list[str],
    repos_touched_today,
    last_commit_timestamp: str | None,
) -> dict:
    return {
        "commits_detected": commits_detected,
        "commits_today_detected": commits_today_detected,
        "session_duration_minutes": 0,
        "session_duration_today_minutes": 0,
        "repos_touched": repos_touched,
        "repos_touched_today": repos_touched_today,
        "marathon_detected": False,
        "session_tracker": None,
        "last_commit_timestamp": last_commit_timestamp,
    }


class StateBuilderMigrationTests(unittest.TestCase):
    def test_existing_state_fills_missing_stats_and_migrates_last_commit_timestamp(self) -> None:
        previous_state = {
            "last_updated": "2026-02-13T09:00:00+00:00",
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "current_streak": 1,
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "total_commits_all_time": 5,
                "last_commit_timestamp": None,
                "recent_active_days": ["2026-02-12"],
                "active_days_total": 5,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            },
        }
        activity = make_activity(
            commits_detected=0,
            commits_today_detected=0,
            repos_touched=[],
            repos_touched_today="not-a-list",
            last_commit_timestamp=None,
        )

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            result = state_builder.calculate_state(previous_state, activity, hours_passed=0)

        self.assertEqual(result["pet"]["stats"], DEFAULT_PET_STATS)
        self.assertEqual(result["github"]["last_commit_timestamp"], "2026-02-13T09:00:00+00:00")
        self.assertEqual(result["github"]["repos_touched_today"], [])
        self.assertIn("session_tracker", result["github"])

    def test_existing_state_without_commit_history_keeps_last_commit_timestamp_none(self) -> None:
        previous_state = {
            "last_updated": "2026-02-13T09:00:00+00:00",
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": DEFAULT_PET_STATS.copy(),
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "current_streak": 0,
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "total_commits_all_time": 0,
                "last_commit_timestamp": None,
                "recent_active_days": [],
                "active_days_total": 0,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            },
        }
        activity = make_activity(
            commits_detected=0,
            commits_today_detected=0,
            repos_touched=[],
            repos_touched_today=[],
            last_commit_timestamp=None,
        )

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            result = state_builder.calculate_state(previous_state, activity, hours_passed=0)

        self.assertIsNone(result["github"]["last_commit_timestamp"])

    def test_initial_state_repos_touched_today_falls_back_to_repos_touched(self) -> None:
        activity = make_activity(
            commits_detected=2,
            commits_today_detected=1,
            repos_touched=["z/repo", "a/repo", "z/repo"],
            repos_touched_today=None,
            last_commit_timestamp="2026-02-13T10:00:00+00:00",
        )

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            result = state_builder.calculate_state(None, activity, hours_passed=0)

        self.assertEqual(result["github"]["commits_today"], 1)
        self.assertEqual(result["github"]["repos_touched_today"], ["a/repo", "z/repo"])
        self.assertEqual(result["github"]["last_commit_timestamp"], "2026-02-13T10:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
