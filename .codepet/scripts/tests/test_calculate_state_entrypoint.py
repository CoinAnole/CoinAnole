import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "calculate_state.py"
SPEC = importlib.util.spec_from_file_location("calculate_state", MODULE_PATH)
CALCULATE_STATE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(CALCULATE_STATE)


class CalculateStateEntrypointSmokeTests(unittest.TestCase):
    def test_compact_activity_removes_redundant_repo_mentions(self) -> None:
        activity = {
            "repos_touched": ["CoinAnole/challenge1"],
            "repos_touched_today": ["CoinAnole/challenge1"],
            "primary_session": {
                "repos_touched": ["CoinAnole/challenge1"],
            },
            "detected_sessions": [
                {"repos_touched": ["CoinAnole/challenge1"]},
            ],
            "session_tracker": {
                "open_session": {"repos_touched": ["CoinAnole/challenge1"]},
            },
        }

        compact = CALCULATE_STATE._compact_activity_for_persistence(activity)

        self.assertNotIn("repos_touched_today", compact)
        self.assertNotIn("repos_touched", compact["primary_session"])
        self.assertNotIn("repos_touched", compact["detected_sessions"][0])
        self.assertNotIn("repos_touched", compact["session_tracker"]["open_session"])
        self.assertEqual(compact["repos_touched"], ["CoinAnole/challenge1"])

    def test_compact_activity_keeps_session_specific_repo_lists(self) -> None:
        activity = {
            "repos_touched": ["CoinAnole/challenge1", "CoinAnole/challenge2"],
            "repos_touched_today": ["CoinAnole/challenge1"],
            "primary_session": {
                "repos_touched": ["CoinAnole/challenge1"],
            },
            "detected_sessions": [
                {"repos_touched": ["CoinAnole/challenge1"]},
                {"repos_touched": ["CoinAnole/challenge2"]},
            ],
            "session_tracker": {
                "open_session": {"repos_touched": ["CoinAnole/challenge2"]},
            },
        }

        compact = CALCULATE_STATE._compact_activity_for_persistence(activity)

        self.assertIn("repos_touched_today", compact)
        self.assertIn("repos_touched", compact["primary_session"])
        self.assertIn("repos_touched", compact["detected_sessions"][0])
        self.assertIn("repos_touched", compact["detected_sessions"][1])
        self.assertIn("repos_touched", compact["session_tracker"]["open_session"])

    @staticmethod
    def _minimal_previous_state(last_updated=None) -> dict:
        state = {
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 50, "energy": 50, "happiness": 50, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "current_streak": 0,
                "longest_streak": 0,
                "commits_today": 0,
                "highest_commits_in_day": 0,
                "longest_session_today_minutes": 0,
                "repos_touched_today": [],
                "last_commit_timestamp": None,
                "total_commits_all_time": 0,
                "recent_active_days": [],
                "active_days_total": 0,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            },
            "image_state": {
                "edit_count_since_reset": 0,
                "total_edits_all_time": 0,
                "last_reset_at": None,
                "reset_count": 0,
                "current_stage_reference": ".codepet/stage_images/baby.png",
            },
            "regrounding": {"should_reground": False, "reason": None, "threshold": 4},
            "evolution": {
                "just_occurred": False,
                "previous_stage": None,
                "new_stage": None,
                "base_reference": None,
                "target_reference": None,
            },
        }
        if last_updated is not None:
            state["last_updated"] = last_updated
        return state

    @staticmethod
    def _write_state_file(state: dict) -> None:
        state_path = Path(".codepet/state.json")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f)

    def test_main_writes_activity_and_state_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("GH_TOKEN", None)
                    os.environ.pop("WATCHED_REPOS", None)
                    os.environ.pop("GITHUB_REPOSITORY", None)

                    exit_code = CALCULATE_STATE.main()

                self.assertEqual(exit_code, 0)

                activity_path = Path(".codepet/activity.json")
                state_path = Path(".codepet/state.json")
                self.assertTrue(activity_path.exists())
                self.assertTrue(state_path.exists())

                with open(activity_path) as f:
                    activity = json.load(f)
                with open(state_path) as f:
                    state = json.load(f)

                self.assertIn("timestamp", activity)
                self.assertIn("activity", activity)
                self.assertIn("calculation", activity)
                self.assertIn("pet", state)
                self.assertIn("github", state)
                self.assertIn("image_state", state)
                self.assertIn("regrounding", state)
            finally:
                os.chdir(old_cwd)

    def test_main_handles_malformed_previous_last_updated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_state_file(self._minimal_previous_state(last_updated="not-a-timestamp"))
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("GH_TOKEN", None)
                    os.environ.pop("WATCHED_REPOS", None)
                    os.environ.pop("GITHUB_REPOSITORY", None)
                    exit_code = CALCULATE_STATE.main()

                self.assertEqual(exit_code, 0)
                with open(".codepet/activity.json", encoding="utf-8") as f:
                    activity = json.load(f)
                self.assertGreaterEqual(activity["calculation"]["hours_since_last_check"], 0)
            finally:
                os.chdir(old_cwd)

    def test_main_handles_missing_previous_last_updated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                self._write_state_file(self._minimal_previous_state(last_updated=None))
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("GH_TOKEN", None)
                    os.environ.pop("WATCHED_REPOS", None)
                    os.environ.pop("GITHUB_REPOSITORY", None)
                    exit_code = CALCULATE_STATE.main()

                self.assertEqual(exit_code, 0)
                with open(".codepet/activity.json", encoding="utf-8") as f:
                    activity = json.load(f)
                self.assertGreaterEqual(activity["calculation"]["hours_since_last_check"], 0)
            finally:
                os.chdir(old_cwd)

    def test_main_clamps_negative_hours_since_last_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                future_last_updated = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
                self._write_state_file(self._minimal_previous_state(last_updated=future_last_updated))
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("GH_TOKEN", None)
                    os.environ.pop("WATCHED_REPOS", None)
                    os.environ.pop("GITHUB_REPOSITORY", None)
                    exit_code = CALCULATE_STATE.main()

                self.assertEqual(exit_code, 0)
                with open(".codepet/activity.json", encoding="utf-8") as f:
                    activity = json.load(f)
                self.assertEqual(activity["calculation"]["hours_since_last_check"], 0.0)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
