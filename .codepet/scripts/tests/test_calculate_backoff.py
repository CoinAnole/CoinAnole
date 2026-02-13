import importlib.util
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "calculate_backoff.py"
SPEC = importlib.util.spec_from_file_location("calculate_backoff", MODULE_PATH)
CALCULATE_BACKOFF = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(CALCULATE_BACKOFF)


def utc_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 2, 13, hour, minute, tzinfo=timezone.utc)


class CalculateBackoffTests(unittest.TestCase):
    def test_parse_iso8601_assumes_utc_for_naive_timestamp(self) -> None:
        parsed = CALCULATE_BACKOFF.parse_iso8601("2026-02-13T12:34:56")
        self.assertEqual(parsed.isoformat(), "2026-02-13T12:34:56+00:00")

    def test_set_output_supports_local_and_github_actions_modes(self) -> None:
        with patch.dict(os.environ, {"GITHUB_OUTPUT": ""}, clear=False), patch("builtins.print") as print_mock:
            CALCULATE_BACKOFF.set_output("example", "value")
        print_mock.assert_any_call("::set-output name=example::value")
        print_mock.assert_any_call("  example=value")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "github_output.txt"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}, clear=False), patch("builtins.print"):
                CALCULATE_BACKOFF.set_output("next_interval", "120")

            self.assertEqual(output_path.read_text(encoding="utf-8"), "next_interval=120\n")

    def test_crossed_interval_boundary_handles_jitter_and_buckets(self) -> None:
        last_activity = utc_time(0, 0)
        current = utc_time(3, 10)

        self.assertTrue(
            CALCULATE_BACKOFF.crossed_interval_boundary(
                last_activity=last_activity,
                previous_check=None,
                current_check=current,
                interval_minutes=120,
            )
        )
        self.assertTrue(
            CALCULATE_BACKOFF.crossed_interval_boundary(
                last_activity=last_activity,
                previous_check=utc_time(1, 59),
                current_check=current,
                interval_minutes=120,
            )
        )
        self.assertFalse(
            CALCULATE_BACKOFF.crossed_interval_boundary(
                last_activity=last_activity,
                previous_check=utc_time(2, 30),
                current_check=current,
                interval_minutes=120,
            )
        )
        self.assertFalse(
            CALCULATE_BACKOFF.crossed_interval_boundary(
                last_activity=last_activity,
                previous_check=utc_time(5, 0),
                current_check=current,
                interval_minutes=120,
            )
        )

    def test_calculate_backoff_tiers(self) -> None:
        last_activity = utc_time(0, 0)

        active = CALCULATE_BACKOFF.calculate_backoff(
            hours_inactive=1,
            current_time=utc_time(1, 0),
            last_activity=last_activity,
            previous_check=utc_time(0, 0),
        )
        self.assertEqual(active["reason"], "active_user")
        self.assertTrue(active["should_trigger"])
        self.assertEqual(active["next_interval"], 60)

        backoff_2hr = CALCULATE_BACKOFF.calculate_backoff(
            hours_inactive=3,
            current_time=utc_time(3, 0),
            last_activity=last_activity,
            previous_check=utc_time(1, 0),
        )
        self.assertEqual(backoff_2hr["reason"], "backoff_2hr")
        self.assertTrue(backoff_2hr["should_trigger"])
        self.assertEqual(backoff_2hr["next_interval"], 120)

        skip_2hr = CALCULATE_BACKOFF.calculate_backoff(
            hours_inactive=3,
            current_time=utc_time(3, 0),
            last_activity=last_activity,
            previous_check=utc_time(2, 30),
        )
        self.assertEqual(skip_2hr["reason"], "skipping_for_backoff")
        self.assertFalse(skip_2hr["should_trigger"])

        backoff_4hr = CALCULATE_BACKOFF.calculate_backoff(
            hours_inactive=6,
            current_time=utc_time(6, 30),
            last_activity=last_activity,
            previous_check=utc_time(3, 30),
        )
        self.assertEqual(backoff_4hr["reason"], "backoff_4hr")
        self.assertTrue(backoff_4hr["should_trigger"])
        self.assertEqual(backoff_4hr["next_interval"], 240)

        backoff_6hr = CALCULATE_BACKOFF.calculate_backoff(
            hours_inactive=9,
            current_time=utc_time(9, 0),
            last_activity=last_activity,
            previous_check=utc_time(5, 50),
        )
        self.assertEqual(backoff_6hr["reason"], "backoff_6hr")
        self.assertTrue(backoff_6hr["should_trigger"])
        self.assertEqual(backoff_6hr["next_interval"], 360)

    def test_read_run_window_and_read_last_activity_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            activity_file = temp_path / "activity.json"
            state_file = temp_path / "state.json"

            activity_file.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-02-13T05:00:00+00:00",
                        "calculation": {"previous_check": "2026-02-13T04:00:00+00:00"},
                        "activity": {
                            "commits_detected": 1,
                            "last_commit_timestamp": "2026-02-13T03:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            state_file.write_text(
                json.dumps({"github": {"last_commit_timestamp": "2026-02-13T02:00:00+00:00"}}),
                encoding="utf-8",
            )

            current_check, previous_check = CALCULATE_BACKOFF.read_run_window(activity_file)
            self.assertEqual(current_check.isoformat(), "2026-02-13T05:00:00+00:00")
            self.assertEqual(previous_check.isoformat(), "2026-02-13T04:00:00+00:00")

            self.assertEqual(
                CALCULATE_BACKOFF.read_last_activity(state_file, activity_file).isoformat(),
                "2026-02-13T02:00:00+00:00",
            )

            state_file.unlink()
            self.assertEqual(
                CALCULATE_BACKOFF.read_last_activity(state_file, activity_file).isoformat(),
                "2026-02-13T03:00:00+00:00",
            )

            activity_file.write_text("{broken", encoding="utf-8")
            malformed_current, malformed_previous = CALCULATE_BACKOFF.read_run_window(activity_file)
            self.assertIsNone(malformed_previous)
            self.assertIsNotNone(malformed_current.tzinfo)
            self.assertIsNone(CALCULATE_BACKOFF.read_last_activity(state_file, activity_file))

    def test_main_first_run_outputs_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            outputs = {}

            def capture_output(key: str, value: str) -> None:
                outputs[key] = value

            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.object(CALCULATE_BACKOFF, "set_output", side_effect=capture_output):
                    exit_code = CALCULATE_BACKOFF.main()
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 0)
            self.assertEqual(outputs["should_trigger"], "true")
            self.assertEqual(outputs["reason"], "first_run")
            self.assertEqual(outputs["next_interval"], "60")
            self.assertEqual(outputs["hours_inactive"], "0")

    def test_main_existing_setup_without_activity_defaults_to_max_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codepet_dir = Path(temp_dir) / ".codepet"
            codepet_dir.mkdir(parents=True, exist_ok=True)
            (codepet_dir / "activity.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-02-13T10:00:00+00:00",
                        "calculation": {"previous_check": "2026-02-13T09:00:00+00:00"},
                        "activity": {"commits_detected": 0},
                    }
                ),
                encoding="utf-8",
            )
            (codepet_dir / "state.json").write_text(
                json.dumps({"github": {"last_commit_timestamp": None}}),
                encoding="utf-8",
            )

            outputs = {}

            def capture_output(key: str, value: str) -> None:
                outputs[key] = value

            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.object(CALCULATE_BACKOFF, "set_output", side_effect=capture_output):
                    exit_code = CALCULATE_BACKOFF.main()
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 0)
            self.assertEqual(outputs["should_trigger"], "false")
            self.assertEqual(outputs["reason"], "skipping_for_backoff")
            self.assertEqual(outputs["next_interval"], "360")
            self.assertEqual(outputs["hours_inactive"], "8")

    def test_main_uses_last_activity_to_calculate_backoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codepet_dir = Path(temp_dir) / ".codepet"
            codepet_dir.mkdir(parents=True, exist_ok=True)
            (codepet_dir / "activity.json").write_text(
                json.dumps(
                    {
                        "timestamp": "2026-02-13T11:00:00+00:00",
                        "calculation": {"previous_check": "2026-02-13T09:00:00+00:00"},
                        "activity": {"commits_detected": 0},
                    }
                ),
                encoding="utf-8",
            )
            (codepet_dir / "state.json").write_text(
                json.dumps({"github": {"last_commit_timestamp": "2026-02-13T08:00:00+00:00"}}),
                encoding="utf-8",
            )

            outputs = {}

            def capture_output(key: str, value: str) -> None:
                outputs[key] = value

            old_cwd = os.getcwd()
            os.chdir(temp_dir)
            try:
                with patch.object(CALCULATE_BACKOFF, "set_output", side_effect=capture_output):
                    exit_code = CALCULATE_BACKOFF.main()
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 0)
            self.assertEqual(outputs["should_trigger"], "true")
            self.assertEqual(outputs["reason"], "backoff_2hr")
            self.assertEqual(outputs["next_interval"], "120")
            self.assertEqual(outputs["hours_inactive"], "3")


if __name__ == "__main__":
    unittest.main()
