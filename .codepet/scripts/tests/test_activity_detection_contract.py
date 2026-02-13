import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc import activity_detection


class ActivityDetectionContractTests(unittest.TestCase):
    def test_detect_activity_without_token_returns_contract(self) -> None:
        now = datetime(2026, 2, 12, 12, 0, tzinfo=timezone.utc)
        last_check = datetime(2026, 2, 12, 11, 0, tzinfo=timezone.utc)

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GH_TOKEN", None)
            os.environ.pop("GITHUB_REPOSITORY", None)

            result = activity_detection.detect_activity(
                watched_repos=["owner/repo"],
                last_check=last_check,
                previous_session_tracker=None,
                now=now,
            )

        required_keys = {
            "commits_detected",
            "commits_today_detected",
            "repos_touched",
            "repos_touched_today",
            "session_duration_minutes",
            "session_duration_today_minutes",
            "marathon_detected",
            "session_split_timeout_minutes",
            "session_count_detected",
            "primary_session",
            "detected_sessions",
            "session_tracker",
            "last_commit_timestamp",
            "social_events",
        }
        self.assertTrue(required_keys.issubset(result.keys()))
        self.assertEqual(result["commits_detected"], 0)
        self.assertEqual(result["repos_touched"], [])
        self.assertIsNone(result["last_commit_timestamp"])
        self.assertIn("stars_received", result["social_events"])

    def test_detect_activity_without_pygithub_returns_contract(self) -> None:
        now = datetime(2026, 2, 12, 12, 0, tzinfo=timezone.utc)
        last_check = datetime(2026, 2, 12, 11, 0, tzinfo=timezone.utc)

        with patch.object(activity_detection, "HAS_GITHUB", False):
            result = activity_detection.detect_activity(
                watched_repos=["owner/repo"],
                last_check=last_check,
                previous_session_tracker={"open_session": None, "last_timeout_minutes": 60},
                now=now,
            )

        self.assertEqual(result["commits_detected"], 0)
        self.assertEqual(result["session_split_timeout_minutes"], 60)
        self.assertIsNone(result["session_tracker"]["open_session"])


if __name__ == "__main__":
    unittest.main()
