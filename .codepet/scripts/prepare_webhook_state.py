#!/usr/bin/env python3
"""
CodePet Pre-Webhook State Preparation

Mutates .codepet/state.json immediately before webhook execution:
- increments image edit counters (anticipating image edit)
- updates re-grounding flags based on threshold
- optionally forces re-grounding via FORCE_REGROUND=true
- exposes outputs for GitHub Actions
"""

import json
import os
import sys
from pathlib import Path
from typing import Any


DEFAULT_THRESHOLD = 6


def to_int(value: Any, default: int = 0) -> int:
    """Best-effort integer conversion with fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def is_truthy(value: Any) -> bool:
    """Interpret common truthy string/boolean values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def set_output(key: str, value: str) -> None:
    """Write outputs for GitHub Actions or local debugging."""
    output_file = os.environ.get("GITHUB_OUTPUT")

    if output_file:
        with open(output_file, "a") as f:
            f.write(f"{key}={value}\n")
    else:
        print(f"::set-output name={key}::{value}")

    print(f"  {key}={value}")


def main() -> int:
    state_file = Path(".codepet/state.json")
    if not state_file.exists():
        print("Error: .codepet/state.json not found")
        return 1

    try:
        with open(state_file) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error loading state file: {e}")
        return 1

    image_state = state.setdefault("image_state", {})
    regrounding = state.setdefault("regrounding", {})

    threshold = to_int(
        regrounding.get("threshold", os.environ.get("REGROUND_THRESHOLD", DEFAULT_THRESHOLD)),
        DEFAULT_THRESHOLD
    )
    threshold = max(1, threshold)
    force_reground = is_truthy(os.environ.get("FORCE_REGROUND", "false"))

    edit_count = max(0, to_int(image_state.get("edit_count_since_reset"), 0)) + 1
    total_edits = max(0, to_int(image_state.get("total_edits_all_time"), 0)) + 1

    image_state["edit_count_since_reset"] = edit_count
    image_state["total_edits_all_time"] = total_edits

    previous_reason = regrounding.get("reason")
    should_reground = bool(regrounding.get("should_reground", False))
    reason = previous_reason

    if force_reground:
        should_reground = True
        reason = "force_reground"
    elif edit_count >= threshold:
        should_reground = True
        if reason in (None, "edit_threshold_reached"):
            reason = "edit_threshold_reached"
    elif reason == "edit_threshold_reached":
        should_reground = False
        reason = None

    regrounding["should_reground"] = should_reground
    regrounding["reason"] = reason
    regrounding["threshold"] = threshold

    try:
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"Error writing state file: {e}")
        return 1

    evolution_just_occurred = bool(state.get("evolution", {}).get("just_occurred", False))
    current_stage_reference = image_state.get("current_stage_reference", "")

    print("Pre-webhook state prepared:")
    print(f"  edit_count_since_reset={edit_count}")
    print(f"  total_edits_all_time={total_edits}")
    print(f"  threshold={threshold}")
    print(f"  force_reground={force_reground}")
    print(f"  should_reground={should_reground}")
    print(f"  reason={reason}")

    set_output("edit_count_since_reset", str(edit_count))
    set_output("total_edits_all_time", str(total_edits))
    set_output("threshold", str(threshold))
    set_output("force_reground", str(force_reground).lower())
    set_output("should_reground", str(should_reground).lower())
    set_output("reason_json", json.dumps(reason))
    set_output("evolution_just_occurred", str(evolution_just_occurred).lower())
    set_output("current_stage_reference", str(current_stage_reference))

    return 0


if __name__ == "__main__":
    sys.exit(main())
