import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "prepare_webhook_state.py"
SPEC = importlib.util.spec_from_file_location("prepare_webhook_state", MODULE_PATH)
PREPARE_WEBHOOK_STATE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(PREPARE_WEBHOOK_STATE)


class PrepareWebhookStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tempdir.name)

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.tempdir.cleanup()

    def write_state(self, state: dict) -> Path:
        state_path = Path(".codepet/state.json")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(state, f)
        return state_path

    def read_state(self) -> dict:
        with open(".codepet/state.json") as f:
            return json.load(f)

    def run_main(self, env_updates: dict[str, str] | None = None) -> tuple[int, dict[str, str]]:
        outputs: dict[str, str] = {}

        def capture_output(key: str, value: str) -> None:
            outputs[key] = value

        env_updates = env_updates or {}
        with patch.object(PREPARE_WEBHOOK_STATE, "set_output", side_effect=capture_output), patch.dict(
            os.environ, env_updates, clear=False
        ):
            exit_code = PREPARE_WEBHOOK_STATE.main()
        return exit_code, outputs

    def test_is_truthy_handles_common_values(self) -> None:
        self.assertTrue(PREPARE_WEBHOOK_STATE.is_truthy(True))
        self.assertTrue(PREPARE_WEBHOOK_STATE.is_truthy("true"))
        self.assertTrue(PREPARE_WEBHOOK_STATE.is_truthy("YES"))
        self.assertTrue(PREPARE_WEBHOOK_STATE.is_truthy("1"))
        self.assertTrue(PREPARE_WEBHOOK_STATE.is_truthy("on"))
        self.assertFalse(PREPARE_WEBHOOK_STATE.is_truthy(False))
        self.assertFalse(PREPARE_WEBHOOK_STATE.is_truthy(None))
        self.assertFalse(PREPARE_WEBHOOK_STATE.is_truthy("0"))
        self.assertFalse(PREPARE_WEBHOOK_STATE.is_truthy("off"))

    def test_to_int_falls_back_for_invalid_values(self) -> None:
        self.assertEqual(PREPARE_WEBHOOK_STATE.to_int("abc", default=7), 7)
        self.assertEqual(PREPARE_WEBHOOK_STATE.to_int(None, default=3), 3)

    def test_set_output_supports_local_and_github_actions_modes(self) -> None:
        with patch.dict(os.environ, {"GITHUB_OUTPUT": ""}, clear=False), patch("builtins.print") as print_mock:
            PREPARE_WEBHOOK_STATE.set_output("example", "value")
        print_mock.assert_any_call("::set-output name=example::value")
        print_mock.assert_any_call("  example=value")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "github_output.txt"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output_path)}, clear=False), patch("builtins.print"):
                PREPARE_WEBHOOK_STATE.set_output("next_interval", "120")

            self.assertEqual(output_path.read_text(encoding="utf-8"), "next_interval=120\n")

    def test_resolve_reground_base_selection_order(self) -> None:
        stage_dir = Path(".codepet/stage_images")
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "baby.png").write_bytes(b"baby")
        (stage_dir / "teen.png").write_bytes(b"teen")

        state = {
            "pet": {"stage": "teen"},
            "evolution": {
                "just_occurred": True,
                "base_reference": ".codepet/stage_images/baby.png",
            },
        }
        image_state = {"current_stage_reference": ".codepet/stage_images/teen.png"}

        path, rule, exists = PREPARE_WEBHOOK_STATE.resolve_reground_base(state, image_state)
        self.assertEqual(path, ".codepet/stage_images/baby.png")
        self.assertEqual(rule, "evolution_base_reference")
        self.assertTrue(exists)

        (stage_dir / "baby.png").unlink()
        path, rule, exists = PREPARE_WEBHOOK_STATE.resolve_reground_base(state, image_state)
        self.assertEqual(path, ".codepet/stage_images/teen.png")
        self.assertEqual(rule, "stage_reference")
        self.assertTrue(exists)

        (stage_dir / "teen.png").unlink()
        Path(".codepet/codepet.png").write_bytes(b"current")
        path, rule, exists = PREPARE_WEBHOOK_STATE.resolve_reground_base(state, image_state)
        self.assertEqual(path, ".codepet/codepet.png")
        self.assertEqual(rule, "bootstrap_codepet_fallback")
        self.assertTrue(exists)

        Path(".codepet/codepet.png").unlink()
        path, rule, exists = PREPARE_WEBHOOK_STATE.resolve_reground_base(state, image_state)
        self.assertEqual(path, ".codepet/stage_images/teen.png")
        self.assertEqual(rule, "missing_base_error")
        self.assertFalse(exists)

    def test_ensure_stage_image_bootstrap_sets_references(self) -> None:
        state = {"pet": {"stage": "adult"}, "evolution": {"just_occurred": False}}
        image_state: dict = {}
        PREPARE_WEBHOOK_STATE.ensure_stage_image_bootstrap(state, image_state)
        self.assertEqual(image_state["current_stage_reference"], ".codepet/stage_images/adult.png")
        self.assertTrue(Path(".codepet/stage_images").exists())

        state = {
            "pet": {"stage": "adult"},
            "evolution": {
                "just_occurred": True,
                "base_reference": ".codepet/stage_images/teen.png",
            },
        }
        image_state = {}
        PREPARE_WEBHOOK_STATE.ensure_stage_image_bootstrap(state, image_state)
        self.assertEqual(image_state["current_stage_reference"], ".codepet/stage_images/teen.png")

    def test_main_returns_error_when_state_is_missing(self) -> None:
        exit_code, outputs = self.run_main({"FORCE_REGROUND": "false"})
        self.assertEqual(exit_code, 1)
        self.assertEqual(outputs, {})

    def test_main_returns_error_on_malformed_state_json(self) -> None:
        state_path = Path(".codepet/state.json")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("{bad", encoding="utf-8")

        exit_code, outputs = self.run_main({"FORCE_REGROUND": "false"})
        self.assertEqual(exit_code, 1)
        self.assertEqual(outputs, {})

    def test_main_returns_error_when_state_write_fails(self) -> None:
        self.write_state(
            {
                "pet": {"stage": "adult"},
                "image_state": {"edit_count_since_reset": 0, "total_edits_all_time": 0},
                "regrounding": {"should_reground": False, "reason": None, "threshold": 6},
                "evolution": {"just_occurred": False},
            }
        )
        real_open = open

        def fail_on_state_write(path, mode="r", *args, **kwargs):
            if str(path).endswith(".codepet/state.json") and "w" in mode:
                raise OSError("simulated write failure")
            return real_open(path, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=fail_on_state_write):
            exit_code, outputs = self.run_main({"FORCE_REGROUND": "false"})

        self.assertEqual(exit_code, 1)
        self.assertEqual(outputs, {})

    def test_main_force_reground_updates_state_and_outputs(self) -> None:
        self.write_state(
            {
                "pet": {"stage": "baby"},
                "image_state": {
                    "edit_count_since_reset": 0,
                    "total_edits_all_time": 4,
                    "reset_count": 1,
                    "last_reset_at": None,
                },
                "regrounding": {
                    "should_reground": False,
                    "reason": None,
                    "threshold": 6,
                },
                "evolution": {"just_occurred": False},
            }
        )
        Path(".codepet/codepet.png").write_bytes(b"current-image")

        exit_code, outputs = self.run_main({"FORCE_REGROUND": "true", "REGROUND_THRESHOLD": "6"})
        self.assertEqual(exit_code, 0)

        state = self.read_state()
        self.assertEqual(state["image_state"]["edit_count_since_reset"], 1)
        self.assertEqual(state["image_state"]["total_edits_all_time"], 5)
        self.assertTrue(state["regrounding"]["should_reground"])
        self.assertEqual(state["regrounding"]["reason"], "force_reground")
        self.assertEqual(state["regrounding"]["threshold"], 6)

        self.assertEqual(outputs["should_reground"], "true")
        self.assertEqual(outputs["reason_json"], "\"force_reground\"")
        self.assertIn("reground_base_image", outputs)
        self.assertIn("reground_base_rule", outputs)
        self.assertIn("reground_base_exists", outputs)

    def test_main_emits_temporal_outputs(self) -> None:
        self.write_state(
            {
                "pet": {
                    "stage": "baby",
                    "derived_state": {"is_sleeping": True, "is_ghost": False, "days_inactive": 1},
                },
                "temporal": {
                    "timezone": "America/Chicago",
                    "local_timestamp": "2026-02-13T22:30:00-06:00",
                    "local_hour": 22,
                    "time_of_day": "night",
                    "time_of_day_transition": "evening_to_night",
                    "is_late_night_coding": True,
                    "inactive_overnight": False,
                },
                "image_state": {
                    "edit_count_since_reset": 0,
                    "total_edits_all_time": 0,
                    "reset_count": 0,
                    "last_reset_at": None,
                },
                "regrounding": {
                    "should_reground": False,
                    "reason": None,
                    "threshold": 6,
                },
                "evolution": {"just_occurred": False},
            }
        )
        Path(".codepet/codepet.png").write_bytes(b"current-image")

        exit_code, outputs = self.run_main({"FORCE_REGROUND": "false"})
        self.assertEqual(exit_code, 0)
        self.assertEqual(outputs["timezone"], "America/Chicago")
        self.assertEqual(outputs["local_timestamp"], "2026-02-13T22:30:00-06:00")
        self.assertEqual(outputs["local_hour"], "22")
        self.assertEqual(outputs["time_of_day"], "night")
        self.assertEqual(outputs["time_of_day_transition"], "evening_to_night")
        self.assertEqual(outputs["is_sleeping"], "true")
        self.assertEqual(outputs["is_late_night_coding"], "true")
        self.assertEqual(outputs["inactive_overnight"], "false")

    def test_main_threshold_trigger_and_stale_reason_reset(self) -> None:
        self.write_state(
            {
                "pet": {"stage": "adult"},
                "image_state": {
                    "edit_count_since_reset": 1,
                    "total_edits_all_time": 1,
                    "reset_count": 0,
                    "last_reset_at": None,
                },
                "regrounding": {
                    "should_reground": False,
                    "reason": None,
                    "threshold": 2,
                },
                "evolution": {"just_occurred": False},
            }
        )
        threshold_code, threshold_outputs = self.run_main({"FORCE_REGROUND": "false"})
        self.assertEqual(threshold_code, 0)
        threshold_state = self.read_state()
        self.assertEqual(threshold_state["image_state"]["edit_count_since_reset"], 2)
        self.assertTrue(threshold_state["regrounding"]["should_reground"])
        self.assertEqual(threshold_state["regrounding"]["reason"], "edit_threshold_reached")
        self.assertEqual(threshold_outputs["reason_json"], "\"edit_threshold_reached\"")

        self.write_state(
            {
                "pet": {"stage": "adult"},
                "image_state": {
                    "edit_count_since_reset": 0,
                    "total_edits_all_time": 10,
                    "reset_count": 2,
                    "last_reset_at": None,
                },
                "regrounding": {
                    "should_reground": True,
                    "reason": "edit_threshold_reached",
                    "threshold": 5,
                },
                "evolution": {"just_occurred": False},
            }
        )
        reset_code, reset_outputs = self.run_main({"FORCE_REGROUND": "false"})
        self.assertEqual(reset_code, 0)
        reset_state = self.read_state()
        self.assertEqual(reset_state["image_state"]["edit_count_since_reset"], 1)
        self.assertFalse(reset_state["regrounding"]["should_reground"])
        self.assertIsNone(reset_state["regrounding"]["reason"])
        self.assertEqual(reset_outputs["reason_json"], "null")


if __name__ == "__main__":
    unittest.main()
