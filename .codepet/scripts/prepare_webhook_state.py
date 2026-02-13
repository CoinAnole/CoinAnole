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


def resolve_reground_base(state: dict, image_state: dict) -> tuple[str, str, bool]:
    """
    Resolve the preferred re-grounding base image path and selection rule.

    Returns:
        (path, rule, exists)
    """
    stage = state.get("pet", {}).get("stage", "baby")
    evolution = state.get("evolution", {})

    evolution_base = evolution.get("base_reference")
    stage_reference = image_state.get("current_stage_reference")
    current_image = ".codepet/codepet.png"

    if evolution.get("just_occurred") and evolution_base:
        if Path(evolution_base).exists():
            return evolution_base, "evolution_base_reference", True

    if stage_reference and Path(stage_reference).exists():
        return stage_reference, "stage_reference", True

    if Path(current_image).exists():
        return current_image, "bootstrap_codepet_fallback", True

    # No viable base file exists; return stage reference for diagnostics.
    fallback = stage_reference or f".codepet/stage_images/{stage}.png"
    return fallback, "missing_base_error", False


def ensure_stage_image_bootstrap(state: dict, image_state: dict) -> None:
    """
    Ensure stage anchor directory exists.

    Manual force-reground can run without calculate_state.py first, so we also
    enforce canonical stage reference paths here.
    """
    stage_dir = Path(".codepet/stage_images")
    stage_dir.mkdir(parents=True, exist_ok=True)

    stage = state.get("pet", {}).get("stage", "baby")
    evolution_just_occurred = bool(state.get("evolution", {}).get("just_occurred", False))
    evolution_base_reference = state.get("evolution", {}).get("base_reference")
    canonical_reference = f".codepet/stage_images/{stage}.png"
    if evolution_just_occurred and evolution_base_reference:
        # Preserve evolution flow: evolve from previous stage anchor first.
        image_state["current_stage_reference"] = evolution_base_reference
    else:
        image_state["current_stage_reference"] = canonical_reference

    if stage == "baby" and not (stage_dir / "baby.png").exists():
        print("Warning: Missing stage anchor .codepet/stage_images/baby.png")


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
    ensure_stage_image_bootstrap(state, image_state)

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
    reground_base_image, reground_base_rule, reground_base_exists = resolve_reground_base(state, image_state)

    print("Pre-webhook state prepared:")
    print(f"  edit_count_since_reset={edit_count}")
    print(f"  total_edits_all_time={total_edits}")
    print(f"  threshold={threshold}")
    print(f"  force_reground={force_reground}")
    print(f"  should_reground={should_reground}")
    print(f"  reason={reason}")
    print(f"  reground_base_image={reground_base_image}")
    print(f"  reground_base_rule={reground_base_rule}")
    print(f"  reground_base_exists={reground_base_exists}")

    set_output("edit_count_since_reset", str(edit_count))
    set_output("total_edits_all_time", str(total_edits))
    set_output("threshold", str(threshold))
    set_output("force_reground", str(force_reground).lower())
    set_output("should_reground", str(should_reground).lower())
    set_output("reason_json", json.dumps(reason))
    set_output("evolution_just_occurred", str(evolution_just_occurred).lower())
    set_output("current_stage_reference", str(current_stage_reference))
    set_output("reground_base_image", str(reground_base_image))
    set_output("reground_base_rule", str(reground_base_rule))
    set_output("reground_base_exists", str(reground_base_exists).lower())

    return 0


if __name__ == "__main__":
    sys.exit(main())
