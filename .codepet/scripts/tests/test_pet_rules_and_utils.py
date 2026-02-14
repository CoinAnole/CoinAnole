import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc import io_utils, pet_rules, time_utils


def pet_with_stats(satiety: float, energy: float, happiness: float) -> dict:
    return {
        "stats": {
            "satiety": satiety,
            "energy": energy,
            "happiness": happiness,
            "social": 50,
        }
    }


class PetRulesAndUtilsTests(unittest.TestCase):
    def test_calculate_mood_all_branches(self) -> None:
        self.assertEqual(
            pet_rules.calculate_mood(
                pet_with_stats(satiety=10, energy=90, happiness=70),
                github_stats={"current_streak": 0},
                repos_touched=[],
            ),
            "starving",
        )
        self.assertEqual(
            pet_rules.calculate_mood(
                pet_with_stats(satiety=30, energy=20, happiness=70),
                github_stats={"current_streak": 0},
                repos_touched=[],
            ),
            "exhausted",
        )
        self.assertEqual(
            pet_rules.calculate_mood(
                pet_with_stats(satiety=30, energy=60, happiness=95),
                github_stats={"current_streak": 4},
                repos_touched=[],
            ),
            "ecstatic",
        )
        self.assertEqual(
            pet_rules.calculate_mood(
                pet_with_stats(satiety=30, energy=60, happiness=50),
                github_stats={"current_streak": 0},
                repos_touched=["r1", "r2", "r3", "r4", "r5", "r6"],
            ),
            "scattered",
        )
        self.assertEqual(
            pet_rules.calculate_mood(
                pet_with_stats(satiety=30, energy=60, happiness=50),
                github_stats={"current_streak": 1},
                repos_touched=["r1"],
            ),
            "content",
        )

    def test_calculate_stage_boundaries(self) -> None:
        self.assertEqual(pet_rules.calculate_stage(0), "baby")
        self.assertEqual(pet_rules.calculate_stage(10), "teen")
        self.assertEqual(pet_rules.calculate_stage(50), "adult")
        self.assertEqual(pet_rules.calculate_stage(200), "elder")

    def test_apply_decay_handles_marathon_active_and_rest_modes(self) -> None:
        marathon_pet = pet_with_stats(satiety=60, energy=50, happiness=60)
        updated_marathon = pet_rules.apply_decay(
            marathon_pet,
            hours_passed=2,
            activity={"marathon_detected": True, "commits_detected": 4},
        )
        self.assertAlmostEqual(updated_marathon["stats"]["satiety"], 58.3333, places=3)
        self.assertAlmostEqual(updated_marathon["stats"]["happiness"], 59.8333, places=3)
        self.assertEqual(updated_marathon["stats"]["energy"], 40)

        active_pet = pet_with_stats(satiety=60, energy=50, happiness=60)
        updated_active = pet_rules.apply_decay(
            active_pet,
            hours_passed=2,
            activity={"marathon_detected": False, "commits_detected": 2},
        )
        self.assertEqual(updated_active["stats"]["energy"], 45)

        rest_pet = pet_with_stats(satiety=60, energy=50, happiness=60)
        updated_rest = pet_rules.apply_decay(
            rest_pet,
            hours_passed=2,
            activity={"marathon_detected": False, "commits_detected": 0},
        )
        self.assertEqual(updated_rest["stats"]["energy"], 60)

    def test_apply_activity_bonuses_and_marathon_penalty(self) -> None:
        pet = pet_with_stats(satiety=90, energy=20, happiness=90)
        updated = pet_rules.apply_activity_bonuses(
            pet,
            activity={
                "commits_detected": 3,
                "repos_touched": ["one/repo", "two/repo"],
                "marathon_detected": True,
            },
        )
        self.assertEqual(updated["stats"]["satiety"], 100)
        self.assertEqual(updated["stats"]["happiness"], 94)
        self.assertEqual(updated["stats"]["energy"], 5)

        unchanged = pet_rules.apply_activity_bonuses(
            pet_with_stats(satiety=50, energy=50, happiness=50),
            activity={"commits_detected": 0, "repos_touched": [], "marathon_detected": False},
        )
        self.assertEqual(unchanged["stats"]["satiety"], 50)
        self.assertEqual(unchanged["stats"]["energy"], 50)
        self.assertEqual(unchanged["stats"]["happiness"], 50)

    def test_trim_active_days_and_streak_validation(self) -> None:
        trimmed = pet_rules.trim_active_days(
            [
                "2026-02-01",
                "2026-02-03",
                "2026-02-02",
                "2026-02-02",
                "2026-02-04",
                "2026-02-05",
                "2026-02-06",
                42,
            ],
            limit=3,
        )
        self.assertEqual(trimmed, ["2026-02-04", "2026-02-05", "2026-02-06"])

        streak = pet_rules.calculate_current_streak(
            {"2026-02-10", "2026-02-11", "2026-02-12"},
            today="2026-02-12",
        )
        self.assertEqual(streak, 3)
        self.assertEqual(pet_rules.calculate_current_streak({"2026-02-11"}, today="2026-02-12"), 0)
        self.assertEqual(pet_rules.calculate_current_streak({"2026-02-11"}, today="bad-date"), 0)

    def test_time_utils_parsing_and_conversion(self) -> None:
        naive = datetime(2026, 2, 13, 10, 0)
        self.assertEqual(time_utils.to_iso8601(naive), "2026-02-13T10:00:00+00:00")
        aware = datetime(2026, 2, 13, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(time_utils.to_iso8601(aware), "2026-02-13T10:00:00+00:00")

        self.assertIsNone(time_utils.parse_iso_datetime(None))
        self.assertIsNone(time_utils.parse_iso_datetime("not-a-timestamp"))
        self.assertEqual(
            time_utils.parse_iso_datetime("2026-02-13T09:30:00").isoformat(),
            "2026-02-13T09:30:00+00:00",
        )
        self.assertEqual(
            time_utils.parse_iso_datetime("2026-02-13T09:30:00Z").isoformat(),
            "2026-02-13T09:30:00+00:00",
        )

        self.assertEqual(time_utils.to_int("7"), 7)
        self.assertEqual(time_utils.to_int("bad", default=3), 3)

    def test_io_utils_load_and_write_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            missing_state = temp_path / "missing.json"
            self.assertIsNone(io_utils.load_previous_state(missing_state))

            bad_state = temp_path / "bad.json"
            bad_state.write_text("{invalid-json", encoding="utf-8")
            self.assertIsNone(io_utils.load_previous_state(bad_state))

            as_directory = temp_path / "state_dir"
            as_directory.mkdir()
            self.assertIsNone(io_utils.load_previous_state(as_directory))

            output_path = temp_path / "nested" / "state.json"
            io_utils.write_json_file(output_path, {"pet": {"name": "Byte"}})
            with open(output_path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded, {"pet": {"name": "Byte"}})


if __name__ == "__main__":
    unittest.main()
