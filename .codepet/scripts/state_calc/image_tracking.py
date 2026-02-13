"""Image tracking and re-grounding state helpers."""

import os
from pathlib import Path

from .constants import DEFAULT_REGROUND_THRESHOLD
from .time_utils import to_int


def get_reground_threshold(previous_state: dict | None) -> int:
    """Resolve re-grounding threshold from env, previous state, or default."""
    env_threshold = os.environ.get("REGROUND_THRESHOLD")
    if env_threshold is not None:
        return max(1, to_int(env_threshold, DEFAULT_REGROUND_THRESHOLD))

    if previous_state:
        previous_threshold = previous_state.get("regrounding", {}).get("threshold")
        return max(1, to_int(previous_threshold, DEFAULT_REGROUND_THRESHOLD))

    return DEFAULT_REGROUND_THRESHOLD


def ensure_stage_image_bootstrap(stage: str) -> None:
    """
    Ensure stage image directory exists.

    Re-grounding anchors live under `.codepet/stage_images/`.
    """
    stage_dir = Path(".codepet/stage_images")
    stage_dir.mkdir(parents=True, exist_ok=True)

    if stage == "baby" and not (stage_dir / "baby.png").exists():
        print("Warning: Missing stage anchor .codepet/stage_images/baby.png")


def build_image_tracking_state(
    previous_state: dict | None,
    current_stage: str,
    previous_stage: str | None,
    threshold: int,
) -> tuple[dict, dict, dict]:
    """
    Build image tracking fields for state.json.

    These fields are runner-tracked metadata used by webhook preparation and
    cloud-agent re-grounding logic.
    """
    previous_image_state = (previous_state or {}).get("image_state", {})
    previous_regrounding = (previous_state or {}).get("regrounding", {})

    stage_changed = previous_stage is not None and previous_stage != current_stage
    ensure_stage_image_bootstrap(current_stage)
    if previous_stage:
        ensure_stage_image_bootstrap(previous_stage)

    if stage_changed:
        base_reference = f".codepet/stage_images/{previous_stage}.png"
        target_reference = f".codepet/stage_images/{current_stage}.png"
        current_stage_reference = base_reference
        evolution = {
            "just_occurred": True,
            "previous_stage": previous_stage,
            "new_stage": current_stage,
            "base_reference": base_reference,
            "target_reference": target_reference,
        }
    else:
        current_stage_reference = f".codepet/stage_images/{current_stage}.png"
        previous_reference = previous_image_state.get("current_stage_reference")
        if previous_reference and Path(current_stage_reference).exists() is False:
            # Migration fallback: keep prior reference only if canonical anchor
            # is not yet available.
            current_stage_reference = previous_reference

        evolution = {
            "just_occurred": False,
            "previous_stage": None,
            "new_stage": None,
            "base_reference": None,
            "target_reference": None,
        }

    image_state = {
        "edit_count_since_reset": max(0, to_int(previous_image_state.get("edit_count_since_reset"), 0)),
        "total_edits_all_time": max(0, to_int(previous_image_state.get("total_edits_all_time"), 0)),
        "last_reset_at": previous_image_state.get("last_reset_at"),
        "reset_count": max(0, to_int(previous_image_state.get("reset_count"), 0)),
        "current_stage_reference": current_stage_reference,
    }

    should_reground = bool(previous_regrounding.get("should_reground", False))
    reason = previous_regrounding.get("reason")

    if image_state["edit_count_since_reset"] >= threshold:
        should_reground = True
        if reason is None:
            reason = "edit_threshold_reached"
    elif reason == "edit_threshold_reached":
        should_reground = False
        reason = None

    regrounding = {
        "should_reground": should_reground,
        "reason": reason,
        "threshold": threshold,
    }

    return image_state, regrounding, evolution
