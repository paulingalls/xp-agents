#!/usr/bin/env python3
"""Stop command hook: quality review gate.

Blocks stop after /simplify has run but before quality review has been
performed. Depends on the simplify gate's tracker to know when simplify
completed for the current loop. Only fires for code file changes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common  # noqa: I001
import simplify_gate


# ---------------------------------------------------------------------------
# Tracker management
# ---------------------------------------------------------------------------


def _tracker_path(smm_dir: Path, agent_id: str) -> Path:
    return smm_dir / f".quality-review-{agent_id}.json"


def _load_tracker(smm_dir: Path, agent_id: str) -> dict:
    try:
        return json.loads(_tracker_path(smm_dir, agent_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}


def _write_tracker(smm_dir: Path, agent_id: str, tracker: dict) -> None:
    _common.write_json_atomic(_tracker_path(smm_dir, agent_id), tracker)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return stderr message if quality review needed, None otherwise."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Validate agent_id early — needed for tracker checks
    agent_id = input_data.get("agent_id", "main")
    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None

    # Fast path: check own tracker first (tiny JSON read).
    # If already ran for any loop_id, read events to verify it's current.
    own_tracker = _load_tracker(smm_dir, agent_id)

    # Fast path: check if simplify has run at all (tiny JSON read).
    # Skip the expensive events read if simplify hasn't completed yet.
    simplify_tracker = simplify_gate.load_tracker(smm_dir, agent_id)
    simplify_loop_id = simplify_tracker.get("loop_id", "")
    if not simplify_loop_id:
        return None

    # Own tracker matches simplify's loop — already reviewed this loop
    if own_tracker.get("loop_id") == simplify_loop_id:
        return None

    # Now read events to verify loop boundary and code changes
    events = _common.read_events_raw(smm_dir)
    if not events:
        return None

    boundary = simplify_gate.find_last_customer_input(events)
    if boundary is None:
        return None

    start_idx, ci_event = boundary
    loop_id = ci_event.get("id", "")

    # Simplify tracker must match current loop
    if simplify_loop_id != loop_id:
        return None

    # Only trigger for code file changes
    if not simplify_gate.has_code_changes_since(events, start_idx):
        return None

    # Write tracker and block
    _write_tracker(smm_dir, agent_id, {"loop_id": loop_id})
    return (
        "Run /xp-quality-review to review code quality before stopping. "
        "Check for skipped /simplify recommendations and Clean Code issues."
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        print(json.dumps({"decision": "block", "reason": result}))
    sys.exit(0)
