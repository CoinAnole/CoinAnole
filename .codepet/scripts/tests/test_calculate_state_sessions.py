import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc import session_analysis as SESSION_ANALYSIS

MODULE_PATH = SCRIPT_DIR / "calculate_state.py"
SPEC = importlib.util.spec_from_file_location("calculate_state", MODULE_PATH)
CALCULATE_STATE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(CALCULATE_STATE)


def make_time(hour: int, minute: int) -> datetime:
    return datetime(2026, 2, 12, hour, minute, tzinfo=timezone.utc)


def make_event(hour: int, minute: int, repo: str = "owner/repo") -> dict:
    return {"timestamp": make_time(hour, minute), "repo": repo}


class SessionFacadeCompatibilityTests(unittest.TestCase):
    def test_facade_re_exports_session_analysis_functions(self) -> None:
        exported_names = [
            "compute_adaptive_timeout",
            "split_into_sessions",
            "select_primary_session",
            "merge_with_open_session",
            "analyze_commit_sessions",
        ]
        for name in exported_names:
            self.assertTrue(hasattr(CALCULATE_STATE, name), f"Missing facade export: {name}")
            self.assertIs(getattr(CALCULATE_STATE, name), getattr(SESSION_ANALYSIS, name))

    def test_facade_all_includes_session_exports(self) -> None:
        expected = {
            "compute_adaptive_timeout",
            "split_into_sessions",
            "select_primary_session",
            "merge_with_open_session",
            "analyze_commit_sessions",
        }
        self.assertTrue(expected.issubset(set(CALCULATE_STATE.__all__)))

    def test_facade_session_behavior_matches_module(self) -> None:
        events = [
            make_event(10, 0),
            make_event(10, 20),
            make_event(12, 0),
        ]
        facade_result = CALCULATE_STATE.analyze_commit_sessions(
            commit_events=events,
            today="2026-02-12",
            now=make_time(12, 5),
            previous_session_tracker=None,
        )
        module_result = SESSION_ANALYSIS.analyze_commit_sessions(
            commit_events=events,
            today="2026-02-12",
            now=make_time(12, 5),
            previous_session_tracker=None,
        )
        self.assertEqual(facade_result, module_result)


if __name__ == "__main__":
    unittest.main()
