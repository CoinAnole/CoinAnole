import os
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc import state_builder


FIXED_NOW = datetime(2026, 2, 13, 12, 0, tzinfo=timezone.utc)
FIXED_TODAY = "2026-02-13"
YESTERDAY = "2026-02-12T12:00:00+00:00"


class StateBuilderTests(unittest.TestCase):
    def test_calculate_state_initializes_new_pet(self) -> None:
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

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            state = state_builder.calculate_state(None, activity, hours_passed=0)

        self.assertEqual(state["pet"]["name"], "Byte")
        self.assertEqual(state["pet"]["stage"], "baby")
        self.assertEqual(state["github"]["commits_today"], 1)
        self.assertEqual(state["github"]["highest_commits_in_day"], 1)
        self.assertEqual(state["github"]["total_commits_all_time"], 2)
        self.assertEqual(state["github"]["current_streak"], 1)
        self.assertEqual(state["github"]["longest_streak"], 1)
        self.assertIn(FIXED_TODAY, state["github"]["recent_active_days"])
        self.assertEqual(state["github"]["active_days_total"], 1)
        self.assertIn("session_tracker", state["github"])
        self.assertIn("image_state", state)
        self.assertIn("regrounding", state)

    def test_calculate_state_rolls_daily_counters_and_updates_totals(self) -> None:
        previous_state = {
            "last_updated": YESTERDAY,
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 9,
                "longest_session_today_minutes": 99,
                "repos_touched_today": ["old/repo"],
                "total_commits_all_time": 10,
                "recent_active_days": ["2026-02-12"],
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
            "regrounding": {"should_reground": False, "reason": None, "threshold": 4},
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

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertEqual(state["github"]["commits_today"], 2)
        self.assertEqual(state["github"]["highest_commits_in_day"], 9)
        self.assertEqual(state["github"]["longest_session_today_minutes"], 20)
        self.assertEqual(state["github"]["total_commits_all_time"], 13)
        self.assertEqual(state["github"]["current_streak"], 2)
        self.assertEqual(state["github"]["longest_streak"], 2)
        self.assertIn("new/repo", state["github"]["repos_touched_today"])
        self.assertEqual(state["pet"]["stage"], "baby")

    def test_calculate_state_streak_continuity_can_exceed_recent_active_days_limit(self) -> None:
        previous_state = {
            "last_updated": YESTERDAY,
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 1,
                "longest_session_today_minutes": 10,
                "repos_touched_today": ["old/repo"],
                "total_commits_all_time": 20,
                "recent_active_days": [
                    "2026-02-06",
                    "2026-02-07",
                    "2026-02-08",
                    "2026-02-09",
                    "2026-02-10",
                    "2026-02-11",
                    "2026-02-12",
                ],
                "active_days_total": 7,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 7,
                "longest_streak": 7,
                "last_commit_timestamp": "2026-02-12T12:00:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        activity = {
            "commits_detected": 1,
            "commits_today_detected": 1,
            "session_duration_minutes": 10,
            "session_duration_today_minutes": 10,
            "repos_touched": ["new/repo"],
            "repos_touched_today": ["new/repo"],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": "2026-02-13T11:00:00+00:00",
        }

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertEqual(state["github"]["current_streak"], 8)
        self.assertEqual(state["github"]["longest_streak"], 8)
        self.assertEqual(state["github"]["highest_commits_in_day"], 1)

    def test_calculate_state_preserves_streak_on_first_no_commit_tick_after_rollover(self) -> None:
        previous_state = {
            "last_updated": "2026-02-12T23:55:00+00:00",
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 4,
                "longest_session_today_minutes": 30,
                "repos_touched_today": ["old/repo"],
                "total_commits_all_time": 20,
                "recent_active_days": [
                    "2026-02-06",
                    "2026-02-07",
                    "2026-02-08",
                    "2026-02-09",
                    "2026-02-10",
                    "2026-02-11",
                    "2026-02-12",
                ],
                "active_days_total": 7,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 7,
                "longest_streak": 7,
                "last_commit_timestamp": "2026-02-12T22:30:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        activity = {
            "commits_detected": 0,
            "commits_today_detected": 0,
            "session_duration_minutes": 0,
            "session_duration_today_minutes": 0,
            "repos_touched": [],
            "repos_touched_today": [],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": None,
        }

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=0.5)

        self.assertEqual(state["github"]["current_streak"], 7)
        self.assertEqual(state["github"]["longest_streak"], 7)

    def test_calculate_state_resets_streak_after_full_missed_day(self) -> None:
        now = datetime(2026, 2, 14, 12, 0, tzinfo=timezone.utc)
        previous_state = {
            "last_updated": "2026-02-13T23:55:00+00:00",
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "repos_touched_today": [],
                "total_commits_all_time": 20,
                "recent_active_days": [
                    "2026-02-06",
                    "2026-02-07",
                    "2026-02-08",
                    "2026-02-09",
                    "2026-02-10",
                    "2026-02-11",
                    "2026-02-12",
                ],
                "active_days_total": 7,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 7,
                "longest_streak": 7,
                "last_commit_timestamp": "2026-02-12T22:30:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        activity = {
            "commits_detected": 0,
            "commits_today_detected": 0,
            "session_duration_minutes": 0,
            "session_duration_today_minutes": 0,
            "repos_touched": [],
            "repos_touched_today": [],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": None,
        }

        with patch.object(state_builder, "get_current_time", return_value=now), patch.object(
            state_builder, "get_today_date", return_value="2026-02-14"
        ):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertEqual(state["github"]["current_streak"], 0)
        self.assertEqual(state["github"]["longest_streak"], 7)

    def test_calculate_state_streak_continuity_survives_rollover_tick_before_commit(self) -> None:
        previous_state = {
            "last_updated": "2026-02-12T23:55:00+00:00",
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 4,
                "longest_session_today_minutes": 30,
                "repos_touched_today": ["old/repo"],
                "total_commits_all_time": 20,
                "recent_active_days": [
                    "2026-02-06",
                    "2026-02-07",
                    "2026-02-08",
                    "2026-02-09",
                    "2026-02-10",
                    "2026-02-11",
                    "2026-02-12",
                ],
                "active_days_total": 7,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 7,
                "longest_streak": 7,
                "last_commit_timestamp": "2026-02-12T22:30:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        rollover_activity = {
            "commits_detected": 0,
            "commits_today_detected": 0,
            "session_duration_minutes": 0,
            "session_duration_today_minutes": 0,
            "repos_touched": [],
            "repos_touched_today": [],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": None,
        }
        later_commit_activity = {
            "commits_detected": 1,
            "commits_today_detected": 1,
            "session_duration_minutes": 10,
            "session_duration_today_minutes": 10,
            "repos_touched": ["new/repo"],
            "repos_touched_today": ["new/repo"],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": "2026-02-13T10:00:00+00:00",
        }

        with patch.object(
            state_builder,
            "get_current_time",
            return_value=datetime(2026, 2, 13, 0, 30, tzinfo=timezone.utc),
        ), patch.object(state_builder, "get_today_date", return_value="2026-02-13"):
            rolled_state = state_builder.calculate_state(previous_state, rollover_activity, hours_passed=0.5)

        with patch.object(
            state_builder,
            "get_current_time",
            return_value=datetime(2026, 2, 13, 11, 0, tzinfo=timezone.utc),
        ), patch.object(state_builder, "get_today_date", return_value="2026-02-13"):
            committed_state = state_builder.calculate_state(rolled_state, later_commit_activity, hours_passed=1.0)

        self.assertEqual(rolled_state["github"]["current_streak"], 7)
        self.assertEqual(committed_state["github"]["current_streak"], 8)
        self.assertEqual(committed_state["github"]["longest_streak"], 8)

    def test_calculate_state_migrates_legacy_hunger_stat_to_satiety(self) -> None:
        previous_state = {
            "last_updated": YESTERDAY,
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"hunger": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "repos_touched_today": [],
                "total_commits_all_time": 10,
                "recent_active_days": ["2026-02-12"],
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
            "regrounding": {"should_reground": False, "reason": None, "threshold": 4},
            "evolution": {
                "just_occurred": False,
                "previous_stage": None,
                "new_stage": None,
                "base_reference": None,
                "target_reference": None,
            },
        }
        activity = {
            "commits_detected": 0,
            "commits_today_detected": 0,
            "session_duration_minutes": 0,
            "session_duration_today_minutes": 0,
            "repos_touched": [],
            "repos_touched_today": [],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": None,
        }

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=0)

        self.assertEqual(state["pet"]["stats"]["satiety"], 60)
        self.assertNotIn("hunger", state["pet"]["stats"])

    def test_calculate_state_does_not_mutate_previous_state_input(self) -> None:
        previous_state = {
            "last_updated": YESTERDAY,
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 1,
                "longest_session_today_minutes": 10,
                "repos_touched_today": ["old/repo"],
                "total_commits_all_time": 10,
                "recent_active_days": ["2026-02-12"],
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
            "regrounding": {"should_reground": False, "reason": None, "threshold": 4},
            "evolution": {
                "just_occurred": False,
                "previous_stage": None,
                "new_stage": None,
                "base_reference": None,
                "target_reference": None,
            },
        }
        original = deepcopy(previous_state)
        activity = {
            "commits_detected": 3,
            "commits_today_detected": 2,
            "session_duration_minutes": 15,
            "session_duration_today_minutes": 20,
            "repos_touched": ["new/repo"],
            "repos_touched_today": ["new/repo"],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": "2026-02-13T11:00:00+00:00",
        }

        with patch.object(state_builder, "get_current_time", return_value=FIXED_NOW), patch.object(
            state_builder, "get_today_date", return_value=FIXED_TODAY
        ):
            state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertEqual(previous_state, original)

    def test_calculate_state_sets_sleeping_true_for_overnight_inactivity(self) -> None:
        now = datetime(2026, 2, 13, 8, 0, tzinfo=timezone.utc)  # 02:00 America/Chicago
        previous_state = {
            "last_updated": "2026-02-13T07:00:00+00:00",
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "repos_touched_today": [],
                "total_commits_all_time": 10,
                "recent_active_days": ["2026-02-12"],
                "active_days_total": 1,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 1,
                "last_commit_timestamp": "2026-02-13T03:00:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        activity = {
            "commits_detected": 0,
            "commits_today_detected": 0,
            "session_duration_minutes": 0,
            "session_duration_today_minutes": 0,
            "repos_touched": [],
            "repos_touched_today": [],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": None,
        }

        with patch.object(state_builder, "get_current_time", return_value=now), patch.object(
            state_builder, "get_today_date", return_value="2026-02-13"
        ), patch.dict(os.environ, {"CODEPET_TIMEZONE": "America/Chicago"}, clear=False):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertTrue(state["pet"]["derived_state"]["is_sleeping"])
        self.assertTrue(state["temporal"]["inactive_overnight"])
        self.assertEqual(state["temporal"]["time_of_day"], "night")

    def test_calculate_state_marks_late_night_coding_and_keeps_awake(self) -> None:
        now = datetime(2026, 2, 13, 4, 30, tzinfo=timezone.utc)  # 22:30 America/Chicago
        previous_state = {
            "last_updated": "2026-02-13T03:30:00+00:00",
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": True, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "repos_touched_today": [],
                "total_commits_all_time": 10,
                "recent_active_days": ["2026-02-12"],
                "active_days_total": 1,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 1,
                "last_commit_timestamp": "2026-02-13T03:00:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        activity = {
            "commits_detected": 1,
            "commits_today_detected": 1,
            "session_duration_minutes": 15,
            "session_duration_today_minutes": 15,
            "repos_touched": ["owner/repo"],
            "repos_touched_today": ["owner/repo"],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": "2026-02-13T04:20:00+00:00",
        }

        with patch.object(state_builder, "get_current_time", return_value=now), patch.object(
            state_builder, "get_today_date", return_value="2026-02-13"
        ), patch.dict(os.environ, {"CODEPET_TIMEZONE": "America/Chicago"}, clear=False):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertTrue(state["temporal"]["is_late_night_coding"])
        self.assertFalse(state["pet"]["derived_state"]["is_sleeping"])
        self.assertEqual(state["temporal"]["time_of_day"], "night")

    def test_calculate_state_detects_evening_to_night_transition(self) -> None:
        now = datetime(2026, 2, 13, 4, 30, tzinfo=timezone.utc)  # 22:30 America/Chicago
        previous_state = {
            "last_updated": "2026-02-13T03:30:00+00:00",
            "temporal": {"time_of_day": "evening"},
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": False, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "repos_touched_today": [],
                "total_commits_all_time": 10,
                "recent_active_days": ["2026-02-12"],
                "active_days_total": 1,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 1,
                "last_commit_timestamp": "2026-02-13T02:00:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        activity = {
            "commits_detected": 0,
            "commits_today_detected": 0,
            "session_duration_minutes": 0,
            "session_duration_today_minutes": 0,
            "repos_touched": [],
            "repos_touched_today": [],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": None,
        }

        with patch.object(state_builder, "get_current_time", return_value=now), patch.object(
            state_builder, "get_today_date", return_value="2026-02-13"
        ), patch.dict(os.environ, {"CODEPET_TIMEZONE": "America/Chicago"}, clear=False):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertEqual(state["temporal"]["time_of_day_transition"], "evening_to_night")

    def test_calculate_state_detects_night_to_morning_transition(self) -> None:
        now = datetime(2026, 2, 13, 13, 15, tzinfo=timezone.utc)  # 07:15 America/Chicago
        previous_state = {
            "last_updated": "2026-02-13T12:15:00+00:00",
            "temporal": {"time_of_day": "night"},
            "pet": {
                "name": "Byte",
                "stage": "baby",
                "stats": {"satiety": 60, "energy": 70, "happiness": 65, "social": 50},
                "mood": "content",
                "derived_state": {"is_sleeping": True, "is_ghost": False, "days_inactive": 0},
            },
            "github": {
                "commits_today": 0,
                "longest_session_today_minutes": 0,
                "repos_touched_today": [],
                "total_commits_all_time": 10,
                "recent_active_days": ["2026-02-12"],
                "active_days_total": 1,
                "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
                "current_streak": 1,
                "last_commit_timestamp": "2026-02-13T08:00:00+00:00",
            },
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 1,
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
        activity = {
            "commits_detected": 0,
            "commits_today_detected": 0,
            "session_duration_minutes": 0,
            "session_duration_today_minutes": 0,
            "repos_touched": [],
            "repos_touched_today": [],
            "marathon_detected": False,
            "session_tracker": {"open_session": None, "last_timeout_minutes": 45},
            "last_commit_timestamp": None,
        }

        with patch.object(state_builder, "get_current_time", return_value=now), patch.object(
            state_builder, "get_today_date", return_value="2026-02-13"
        ), patch.dict(os.environ, {"CODEPET_TIMEZONE": "America/Chicago"}, clear=False):
            state = state_builder.calculate_state(previous_state, activity, hours_passed=1.0)

        self.assertEqual(state["temporal"]["time_of_day_transition"], "night_to_morning")


if __name__ == "__main__":
    unittest.main()
