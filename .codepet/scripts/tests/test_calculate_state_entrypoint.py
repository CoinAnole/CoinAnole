import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "calculate_state.py"
SPEC = importlib.util.spec_from_file_location("calculate_state", MODULE_PATH)
CALCULATE_STATE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(CALCULATE_STATE)


class CalculateStateEntrypointSmokeTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
