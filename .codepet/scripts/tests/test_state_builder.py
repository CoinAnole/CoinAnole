import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc.state_builder import calculate_state


class StateBuilderTests(unittest.TestCase):
    def test_calculate_state_initializes_new_pet(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        activity = {
            "commits_detected": 2,
            "commits_today_detected": 1,
            "session_duration_minutes": 30,
            "session_duration_today_minutes": 25,
            "repos_touched": ["owner/repo"],
            "repos_touched_today": ["owner/repo"],
            "marathon_detected": False,
            "session_tracker": None,
            "last_commit_timestamp": "2026-02-12T10:00:00+00:00",
        }

        state = calculate_state(None, activity, hours_passed=0)

        self.assertEqual(state["pet"]["name"], "Byte")
        self.assertEqual(state["pet"]["stage"], "baby")
        self.assertEqual(state["github"]["commits_today"], 1)
        self.assertEqual(state["github"]["total_commits_all_time"], 2)
        self.assertIn(today, state["github"]["recent_active_days"])
        self.assertEqual(state["github"]["active_days_total"], 1)
        self.assertIn("session_tracker", state["github"])
        self.assertIn("image_state", state)
        self.assertIn("regrounding", state)

    def test_calculate_state_rolls_daily_counters_and_updates_totals(self) -> None:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        previous_state = {
            "last_updated": yesterday,
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"hunger": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 9,
                "longest_session_today_minutes": 99,
                "repos_touched_today": ["old/repo"],
                "total_commits_all_time": 10,
                "recent_active_days": [(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")],
                "active_days_total": 1,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 1,
                "last_commit_timestamp": None,
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
                "last_reset_at": None,
                "reset_count": 0,
                "current_stage_reference": ".codepet/stage_images/baby.png",
            },
            "regrounding": {"should_reground": False, "reason": None, "threshold": 6},
            "evolution": {
                "just_occurred": False,
                "previous_stage": None,
                "new_stage": None,
                "base_reference": None,
                "target_reference": None,
            },
        }
        activity = {
            "commits_detected": 3,
            "commits_today_detected": 2,
            "session_duration_minutes": 15,
            "session_duration_today_minutes": 20,
            "repos_touched": ["new/repo"],
            "repos_touched_today": ["new/repo"],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": "2026-02-12T12:00:00+00:00",
        }

        state = calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertEqual(state["github"]["commits_today"], 2)
        self.assertEqual(state["github"]["longest_session_today_minutes"], 20)
        self.assertEqual(state["github"]["total_commits_all_time"], 13)
        self.assertIn("new/repo", state["github"]["repos_touched_today"])
        self.assertEqual(state["pet"]["stage"], "baby")


if __name__ == "__main__":
    unittest.main()
