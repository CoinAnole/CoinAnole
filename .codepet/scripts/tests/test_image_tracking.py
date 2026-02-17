import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc.image_tracking import build_image_tracking_state, get_reground_threshold


class ImageTrackingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tempdir.name)

    def tearDown(self) -> None:
        os.chdir(self.old_cwd)
        self.tempdir.cleanup()

    def test_build_image_tracking_state_stage_change_sets_evolution_fields(self) -> None:
        stage_dir = Path(".codepet/stage_images")
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "baby.png").write_bytes(b"stub")

        previous_state = {
            "image_state": {
                "edit_count_since_reset": 2,
                "total_edits_all_time": 5,
                "last_reset_at": None,
                "reset_count": 0,
                "current_stage_reference": ".codepet/stage_images/baby.png",
            },
            "regrounding": {"should_reground": False, "reason": None, "threshold": 6},
        }

        image_state, regrounding, evolution = build_image_tracking_state(
            previous_state=previous_state,
            current_stage="teen",
            previous_stage="baby",
            threshold=6,
        )

        self.assertTrue(evolution["just_occurred"])
        self.assertEqual(evolution["base_reference"], ".codepet/stage_images/baby.png")
        self.assertEqual(evolution["target_reference"], ".codepet/stage_images/teen.png")
        self.assertEqual(image_state["current_stage_reference"], ".codepet/stage_images/baby.png")
        self.assertFalse(regrounding["should_reground"])

    def test_build_image_tracking_state_sets_threshold_reground_reason(self) -> None:
        stage_dir = Path(".codepet/stage_images")
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "baby.png").write_bytes(b"stub")

        previous_state = {
            "image_state": {
                "edit_count_since_reset": 6,
                "total_edits_all_time": 10,
                "last_reset_at": None,
                "reset_count": 1,
                "current_stage_reference": ".codepet/stage_images/baby.png",
            },
            "regrounding": {"should_reground": False, "reason": None, "threshold": 6},
        }

        _, regrounding, evolution = build_image_tracking_state(
            previous_state=previous_state,
            current_stage="baby",
            previous_stage="baby",
            threshold=6,
        )

        self.assertFalse(evolution["just_occurred"])
        self.assertTrue(regrounding["should_reground"])
        self.assertEqual(regrounding["reason"], "edit_threshold_reached")

    def test_get_reground_threshold_prefers_env_then_previous_then_default(self) -> None:
        with patch.dict(os.environ, {"REGROUND_THRESHOLD": "0"}, clear=False):
            self.assertEqual(get_reground_threshold(previous_state={"regrounding": {"threshold": 9}}), 1)

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_reground_threshold(previous_state={"regrounding": {"threshold": "7"}}), 7)
            self.assertEqual(get_reground_threshold(previous_state=None), 6)

    def test_build_image_tracking_state_keeps_previous_reference_when_anchor_missing(self) -> None:
        Path(".codepet/stage_images").mkdir(parents=True, exist_ok=True)
        previous_state = {
            "image_state": {
                "edit_count_since_reset": 1,
                "total_edits_all_time": 3,
                "last_reset_at": None,
                "reset_count": 0,
                "last_counted_image_revision": "git_blob:abc123",
                "current_stage_reference": ".codepet/stage_images/custom_anchor.png",
            },
            "regrounding": {"should_reground": False, "reason": None, "threshold": 6},
        }

        image_state, _, evolution = build_image_tracking_state(
            previous_state=previous_state,
            current_stage="adult",
            previous_stage="adult",
            threshold=6,
        )

        self.assertFalse(evolution["just_occurred"])
        self.assertEqual(image_state["current_stage_reference"], ".codepet/stage_images/custom_anchor.png")
        self.assertEqual(image_state["last_counted_image_revision"], "git_blob:abc123")

    def test_build_image_tracking_state_clears_stale_threshold_reason(self) -> None:
        stage_dir = Path(".codepet/stage_images")
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "baby.png").write_bytes(b"stub")

        previous_state = {
            "image_state": {
                "edit_count_since_reset": 0,
                "total_edits_all_time": 10,
                "last_reset_at": None,
                "reset_count": 2,
                "current_stage_reference": ".codepet/stage_images/baby.png",
            },
            "regrounding": {"should_reground": True, "reason": "edit_threshold_reached", "threshold": 6},
        }

        _, regrounding, _ = build_image_tracking_state(
            previous_state=previous_state,
            current_stage="baby",
            previous_stage="baby",
            threshold=6,
        )

        self.assertFalse(regrounding["should_reground"])
        self.assertIsNone(regrounding["reason"])


if __name__ == "__main__":
    unittest.main()
