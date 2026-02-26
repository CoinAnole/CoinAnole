#!/usr/bin/env python3
"""
CodePet Pre-Webhook State Preparation

Mutates .codepet/state.json immediately before webhook execution:
- reconciles image edit counters against the latest codepet.png revision
- updates re-grounding flags based on threshold
- optionally forces re-grounding via FORCE_REGROUND=true
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from state_calc.constants import DEFAULT_REGROUND_THRESHOLD
from state_calc.output_utils import set_output as _set_output
from state_calc.time_utils import to_int


DEFAULT_THRESHOLD = DEFAULT_REGROUND_THRESHOLD
CODEPET_IMAGE_PATH = ".codepet/codepet.png"
LAST_COUNTED_IMAGE_REVISION_KEY = "last_counted_image_revision"


def is_truthy(value: Any) -> bool:
    """Interpret common truthy string/boolean values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def set_output(key: str, value: str) -> None:
    """Compatibility wrapper around the shared output helper."""
    _set_output(key, value)


def get_current_image_revision(image_path: str = CODEPET_IMAGE_PATH) -> str | None:
    """
    Resolve a stable revision id for the current image.

    Preferred source is the git blob id at HEAD. This works with shallow clones
    and tracks committed image versions. If git metadata is unavailable, fall
    back to a content hash of the working-tree file.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"HEAD:{image_path}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None

    blob_id = result.stdout.strip() if result else ""
    if result and result.returncode == 0 and blob_id:
        return f"git_blob:{blob_id}"

    image_file = Path(image_path)
    if not image_file.exists():
        return None

    try:
        digest = hashlib.sha256(image_file.read_bytes()).hexdigest()
    except OSError:
        return None

    return f"file_sha256:{digest}"


def reconcile_image_edit_counters(image_state: dict, current_revision: str | None) -> tuple[int, int, bool]:
    """
    Increment counters only when a new image revision appears.

    A missing marker is treated as migration/bootstrap and does not increment.
    """
    edit_count = max(0, to_int(image_state.get("edit_count_since_reset"), 0))
    total_edits = max(0, to_int(image_state.get("total_edits_all_time"), 0))
    last_counted_revision = image_state.get(LAST_COUNTED_IMAGE_REVISION_KEY)
    incremented = False

    if current_revision:
        if isinstance(last_counted_revision, str) and last_counted_revision:
            if current_revision != last_counted_revision:
                edit_count += 1
                total_edits += 1
                incremented = True

        image_state[LAST_COUNTED_IMAGE_REVISION_KEY] = current_revision

    image_state["edit_count_since_reset"] = edit_count
    image_state["total_edits_all_time"] = total_edits
    return edit_count, total_edits, incremented


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

    current_image_revision = get_current_image_revision()
    edit_count, total_edits, image_count_incremented = reconcile_image_edit_counters(
        image_state, current_image_revision
    )

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

    current_stage_reference = image_state.get("current_stage_reference", "")
    reground_base_image, reground_base_rule, reground_base_exists = resolve_reground_base(state, image_state)

    print("Pre-webhook state prepared:")
    print(f"  edit_count_since_reset={edit_count}")
    print(f"  total_edits_all_time={total_edits}")
    print(f"  current_image_revision={current_image_revision}")
    print(f"  image_count_incremented={image_count_incremented}")
    print(f"  threshold={threshold}")
    print(f"  force_reground={force_reground}")
    print(f"  should_reground={should_reground}")
    print(f"  reason={reason}")
    print(f"  current_stage_reference={current_stage_reference}")
    print(f"  reground_base_image={reground_base_image}")
    print(f"  reground_base_rule={reground_base_rule}")
    print(f"  reground_base_exists={reground_base_exists}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
