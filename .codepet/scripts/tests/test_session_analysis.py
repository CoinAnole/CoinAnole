import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc import session_analysis as SESSION_ANALYSIS


def make_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 2, 12, hour, minute, tzinfo=timezone.utc)


def make_event(hour: int, minute: int, repo: str = "owner/repo") -> dict:
    return {"timestamp": make_time(hour, minute), "repo": repo}


class SessionAnalysisLogicTests(unittest.TestCase):
    def test_compute_adaptive_timeout_clamps(self) -> None:
        self.assertEqual(SESSION_ANALYSIS.compute_adaptive_timeout([5.0, 6.0], None), 45)
        self.assertEqual(SESSION_ANALYSIS.compute_adaptive_timeout([40.0, 45.0], None), 90)
        self.assertEqual(SESSION_ANALYSIS.compute_adaptive_timeout([], 60), 60)
        self.assertEqual(SESSION_ANALYSIS.compute_adaptive_timeout([], None), 45)

    def test_split_into_sessions_respects_gap_rule(self) -> None:
        events = [
            make_event(10, 0),
            make_event(10, 20),
            make_event(10, 50),
            make_event(12, 0),
        ]
        sessions = SESSION_ANALYSIS.split_into_sessions(events, split_timeout=45)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(len(sessions[0]), 3)
        self.assertEqual(len(sessions[1]), 1)

    def test_primary_session_tie_break(self) -> None:
        summaries = [
            {
                "start": "2026-02-12T10:00:00+00:00",
                "end": "2026-02-12T11:00:00+00:00",
                "duration_minutes": 60,
                "commit_count": 3,
                "repos_touched": ["a/b"],
            },
            {
                "start": "2026-02-12T12:00:00+00:00",
                "end": "2026-02-12T13:00:00+00:00",
                "duration_minutes": 60,
                "commit_count": 4,
                "repos_touched": ["a/c"],
            },
        ]
        primary = SESSION_ANALYSIS.select_primary_session(summaries)
        assert primary is not None
        self.assertEqual(primary["commit_count"], 4)

    def test_merge_with_open_session_window(self) -> None:
        open_session = {
            "start": "2026-02-12T10:00:00+00:00",
            "last_commit": "2026-02-12T10:40:00+00:00",
            "commit_count": 3,
            "repos_touched": ["owner/repo"],
            "split_timeout_minutes": 45,
        }
        self.assertTrue(SESSION_ANALYSIS.merge_with_open_session(open_session, make_time(11, 0)))
        self.assertFalse(SESSION_ANALYSIS.merge_with_open_session(open_session, make_time(12, 0)))

    def test_open_session_expires_without_new_commits(self) -> None:
        previous_tracker = {
            "open_session": {
                "start": "2026-02-12T08:00:00+00:00",
                "last_commit": "2026-02-12T08:15:00+00:00",
                "commit_count": 2,
                "repos_touched": ["owner/repo"],
                "split_timeout_minutes": 45,
            },
            "last_timeout_minutes": 45,
        }
        analysis = SESSION_ANALYSIS.analyze_commit_sessions(
            commit_events=[],
            today="2026-02-12",
            now=make_time(9, 5),
            previous_session_tracker=previous_tracker,
        )
        self.assertIsNone(analysis["session_tracker"]["open_session"])
        self.assertEqual(analysis["session_duration_minutes"], 0)

    def test_marathon_detected_across_runs(self) -> None:
        previous_tracker = {
            "open_session": {
                "start": "2026-02-12T10:00:00+00:00",
                "last_commit": "2026-02-12T10:50:00+00:00",
                "commit_count": 4,
                "repos_touched": ["owner/repo"],
                "split_timeout_minutes": 45,
            },
            "last_timeout_minutes": 45,
        }
        analysis = SESSION_ANALYSIS.analyze_commit_sessions(
            commit_events=[
                make_event(11, 10),
                make_event(11, 40),
                make_event(12, 15),
            ],
            today="2026-02-12",
            now=make_time(12, 20),
            previous_session_tracker=previous_tracker,
        )
        self.assertTrue(analysis["marathon_detected"])
        self.assertEqual(analysis["session_duration_minutes"], 135)
        self.assertEqual(analysis["session_count_detected"], 1)
        self.assertIsNotNone(analysis["session_tracker"]["open_session"])

    def test_isolated_commits_do_not_trigger_marathon(self) -> None:
        analysis = SESSION_ANALYSIS.analyze_commit_sessions(
            commit_events=[
                make_event(10, 0),
                make_event(13, 0),
                make_event(16, 0),
            ],
            today="2026-02-12",
            now=make_time(16, 5),
            previous_session_tracker=None,
        )
        self.assertFalse(analysis["marathon_detected"])
        self.assertEqual(analysis["session_count_detected"], 3)
        self.assertEqual(analysis["session_duration_minutes"], 10)


if __name__ == "__main__":
    unittest.main()
