#!/usr/bin/env python3
"""Stop command hook: auto-simplify gate.

Blocks stop (exit 2) when files were modified in the current loop and
/simplify hasn't been run yet. Uses a tracker file keyed on the last
customer_input event ID to detect new loops.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common

# ---------------------------------------------------------------------------
# Loop boundary detection
# ---------------------------------------------------------------------------


def _find_last_customer_input(events: list[dict]) -> tuple[int, dict] | None:
    """Find last customer_input event. Returns (index, event) or None."""
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("type") == _common.CUSTOMER_INPUT:
            return (i, events[i])
    return None


def _has_file_changes_since(events: list[dict], start_idx: int) -> bool:
    """Check for status events with non-empty working_on after start_idx."""
    for e in events[start_idx + 1 :]:
        if e.get("type") == _common.STATUS:
            working_on = e.get("working_on", [])
            if isinstance(working_on, list) and working_on:
                return True
    return False


# ---------------------------------------------------------------------------
# Tracker management
# ---------------------------------------------------------------------------


def _tracker_path(smm_dir: Path, agent_id: str) -> Path:
    return smm_dir / f".simplify-{agent_id}.json"


def _load_tracker(smm_dir: Path, agent_id: str) -> dict:
    try:
        return json.loads(_tracker_path(smm_dir, agent_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}


def _write_tracker(smm_dir: Path, agent_id: str, tracker: dict) -> None:
    """Atomic write of simplify tracker file."""
    _common.write_json_atomic(_tracker_path(smm_dir, agent_id), tracker)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return stderr message if simplify needed, None otherwise."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_raw(smm_dir)
    if not events:
        return None

    boundary = _find_last_customer_input(events)
    if boundary is None:
        return None

    start_idx, ci_event = boundary
    if not _has_file_changes_since(events, start_idx):
        return None

    # Check tracker — same loop_id means simplify already ran
    agent_id = input_data.get("agent_id", "main")
    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None
    loop_id = ci_event.get("id", "")
    tracker = _load_tracker(smm_dir, agent_id)
    if tracker.get("loop_id") == loop_id:
        return None

    # Write tracker and block
    _write_tracker(smm_dir, agent_id, {"loop_id": loop_id})
    return "Files were modified in this loop. Run /simplify before stopping."


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        print(result, file=sys.stderr)
        sys.exit(2)
    sys.exit(0)
