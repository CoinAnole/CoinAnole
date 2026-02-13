import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


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

    def test_duration_and_summarize_guard_paths(self) -> None:
        self.assertEqual(SESSION_ANALYSIS.calculate_session_duration_minutes(None, make_time(10, 0), 2), 0)
        self.assertEqual(SESSION_ANALYSIS.calculate_session_duration_minutes(make_time(10, 0), None, 2), 0)
        self.assertEqual(SESSION_ANALYSIS.calculate_session_duration_minutes(make_time(10, 0), make_time(10, 0), 0), 0)
        self.assertIsNone(SESSION_ANALYSIS.summarize_session([]))
        self.assertIsNone(SESSION_ANALYSIS.summarize_session([{"timestamp": "bad", "repo": "owner/repo"}]))

    def test_split_into_sessions_handles_invalid_and_naive_timestamps(self) -> None:
        naive = datetime(2026, 2, 12, 10, 0)
        events = [
            {"timestamp": "bad", "repo": "owner/repo"},
            {"timestamp": naive, "repo": "owner/repo"},
            make_event(10, 20),
        ]
        sessions = SESSION_ANALYSIS.split_into_sessions(events, split_timeout=45)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(sessions[0]), 2)
        self.assertEqual(sessions[0][0]["timestamp"].tzinfo, timezone.utc)

        self.assertEqual(
            SESSION_ANALYSIS.split_into_sessions([{"timestamp": "invalid", "repo": "owner/repo"}], split_timeout=45),
            [],
        )

    def test_merge_with_open_session_guards_and_naive_commit_time(self) -> None:
        self.assertFalse(
            SESSION_ANALYSIS.merge_with_open_session(
                {"start": "2026-02-12T10:00:00+00:00", "split_timeout_minutes": 45},
                make_time(10, 30),
            )
        )

        open_session = {
            "start": "2026-02-12T10:00:00+00:00",
            "last_commit": "2026-02-12T10:20:00+00:00",
            "commit_count": 2,
            "repos_touched": ["owner/repo"],
            "split_timeout_minutes": 45,
        }
        naive_new_commit = datetime(2026, 2, 12, 10, 40)
        self.assertTrue(SESSION_ANALYSIS.merge_with_open_session(open_session, naive_new_commit))

    def test_normalize_open_session_handles_invalid_shapes(self) -> None:
        self.assertIsNone(
            SESSION_ANALYSIS.normalize_open_session(
                {
                    "last_commit": "2026-02-12T10:10:00+00:00",
                    "commit_count": 2,
                    "repos_touched": ["owner/repo"],
                }
            )
        )
        self.assertIsNone(
            SESSION_ANALYSIS.normalize_open_session(
                {
                    "start": "2026-02-12T10:00:00+00:00",
                    "last_commit": "2026-02-12T10:10:00+00:00",
                    "commit_count": 0,
                }
            )
        )

        normalized = SESSION_ANALYSIS.normalize_open_session(
            {
                "start": "2026-02-12T10:00:00+00:00",
                "last_commit": "2026-02-12T10:10:00+00:00",
                "commit_count": 3,
                "repos_touched": "owner/repo",
                "split_timeout_minutes": "bad",
            }
        )
        assert normalized is not None
        self.assertEqual(normalized["repos_touched"], [])
        self.assertEqual(normalized["split_timeout_minutes"], 45)

    def test_merge_open_session_into_summary_handles_invalid_inputs_and_repo_types(self) -> None:
        summary = {
            "start": "2026-02-12T10:30:00+00:00",
            "end": "2026-02-12T10:40:00+00:00",
            "duration_minutes": 10,
            "commit_count": 1,
            "repos_touched": ["owner/new"],
        }
        self.assertEqual(
            SESSION_ANALYSIS.merge_open_session_into_summary(
                {"start": "bad", "last_commit": "2026-02-12T10:20:00+00:00", "commit_count": 2},
                summary,
            ),
            summary,
        )

        merged = SESSION_ANALYSIS.merge_open_session_into_summary(
            {
                "start": "2026-02-12T10:00:00+00:00",
                "last_commit": "2026-02-12T10:20:00+00:00",
                "commit_count": 2,
                "repos_touched": "owner/open",
            },
            {
                "start": "2026-02-12T10:30:00+00:00",
                "end": "2026-02-12T10:40:00+00:00",
                "duration_minutes": 10,
                "commit_count": 1,
                "repos_touched": "owner/new",
            },
        )
        self.assertEqual(merged["commit_count"], 3)
        self.assertEqual(merged["repos_touched"], [])

    def test_analyze_commit_sessions_keeps_recent_open_session_without_new_events(self) -> None:
        previous_tracker = {
            "open_session": {
                "start": "2026-02-12T08:00:00+00:00",
                "last_commit": "2026-02-12T08:40:00+00:00",
                "commit_count": 3,
                "repos_touched": ["owner/repo"],
                "split_timeout_minutes": 45,
            },
            "last_timeout_minutes": 45,
        }
        analysis = SESSION_ANALYSIS.analyze_commit_sessions(
            commit_events=[],
            today="2026-02-12",
            now=make_time(9, 0),
            previous_session_tracker=previous_tracker,
        )
        self.assertIsNotNone(analysis["session_tracker"]["open_session"])
        self.assertEqual(analysis["session_tracker"]["open_session"]["commit_count"], 3)

    def test_analyze_commit_sessions_handles_invalid_events_naive_times_and_non_list_repos(self) -> None:
        naive = datetime(2026, 2, 12, 10, 0)
        events = [
            {"timestamp": "invalid", "repo": "owner/repo"},
            {"timestamp": naive, "repo": 123},
        ]
        summary = {
            "start": "2026-02-12T10:00:00+00:00",
            "end": "2026-02-12T10:10:00+00:00",
            "duration_minutes": 10,
            "commit_count": 1,
            "repos_touched": "owner/repo",
        }
        with patch.object(SESSION_ANALYSIS, "summarize_session", return_value=summary):
            analysis = SESSION_ANALYSIS.analyze_commit_sessions(
                commit_events=events,
                today="2026-02-12",
                now=make_time(10, 12),
                previous_session_tracker=None,
            )

        self.assertEqual(analysis["session_count_detected"], 1)
        open_session = analysis["session_tracker"]["open_session"]
        assert open_session is not None
        self.assertEqual(open_session["repos_touched"], [])

    def test_analyze_commit_sessions_accepts_naive_now(self) -> None:
        analysis = SESSION_ANALYSIS.analyze_commit_sessions(
            commit_events=[make_event(10, 0)],
            today="2026-02-12",
            now=datetime(2026, 2, 12, 10, 20),
            previous_session_tracker=None,
        )
        self.assertEqual(analysis["session_count_detected"], 1)
        open_session = analysis["session_tracker"]["open_session"]
        assert open_session is not None
        self.assertEqual(open_session["last_commit"], "2026-02-12T10:00:00+00:00")

    def test_merge_open_session_into_summary_sanitizes_repo_lists(self) -> None:
        merged = SESSION_ANALYSIS.merge_open_session_into_summary(
            {
                "start": "2026-02-12T10:00:00+00:00",
                "last_commit": "2026-02-12T10:20:00+00:00",
                "commit_count": 2,
                "repos_touched": ["owner/open", "", None, "owner/open", 123],
            },
            {
                "start": "2026-02-12T10:30:00+00:00",
                "end": "2026-02-12T10:40:00+00:00",
                "duration_minutes": 10,
                "commit_count": 1,
                "repos_touched": ["owner/new", "owner/open", False],
            },
        )
        self.assertEqual(merged["repos_touched"], ["owner/new", "owner/open"])


if __name__ == "__main__":
    unittest.main()
