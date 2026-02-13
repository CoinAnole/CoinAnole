"""JSON file IO helpers for state calculation."""

import json
from pathlib import Path


def load_previous_state(state_file: Path) -> dict | None:
    """Load previous state from state.json if it exists."""
    if not state_file.exists():
        return None

    try:
        with open(state_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load previous state: {e}")
        return None


def write_json_file(path: Path, data: dict) -> None:
    """Write data to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
