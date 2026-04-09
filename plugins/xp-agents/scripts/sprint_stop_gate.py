#!/usr/bin/env python3
"""Stop command hook: unified sprint lifecycle gate.

Replaces accept_gate.py. Handles the sprint cascade (accept → review):
  1. in-progress stories + ACCEPT marker → block "run /xp-accept"
  2. sprint complete, no sprint_end event → block "run /xp-sprint-review"

Sprint retrospective is NOT part of the Stop cascade. It runs at the
start of the next session via retrospective.py, which detects a
dangling sprint_end and branches to sprint-retro prep.

Common deferrals (review cycle active, teammates active) apply to all
steps so the main agent can continue its current workflow without being
blocked mid-cycle.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import markers
import sprint_parser
import sprint_state
from event_schema import EVENT_TYPE_SPRINT, SPRINT_ACTION_END

_ACCEPT_MESSAGE = (
    "Stories are in-progress. Run /xp-accept to verify "
    "acceptance criteria before stopping."
)

_REVIEW_MESSAGE = (
    "Sprint complete. Run /xp-sprint-review to review what shipped before stopping."
)

_REVIEW_FLAGS = ("simplify_done", "quality_review_done", "security_review_done")


def _deferred(smm_dir: Path, agent_id: str) -> bool:
    """Return True if we should defer blocking (mid-workflow, teammates active)."""
    # Mid-AskUserQuestion dialogue — cheapest check, most common interactive hit
    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return True
    cycle = markers.read_review_cycle(smm_dir, agent_id)
    if any(cycle.get(f) for f in _REVIEW_FLAGS):
        return True
    coord = coordination.read_coordination(smm_dir)
    return any(aid != agent_id for aid in coord)


def _sprint_id_from_content(content: str) -> str:
    """Return sprint_id from sprint.md content, or empty string if missing."""
    return sprint_parser.parse_sprint_data(content).get("sprint_id") or ""


def _has_sprint_end_event(events: list[dict], sprint_id: str) -> bool:
    """Return True if a sprint_end event for the given sprint_id exists."""
    for event in reversed(events):
        if event.get("type") != EVENT_TYPE_SPRINT:
            continue
        metadata = event.get("metadata") or {}
        if (
            metadata.get("action") == SPRINT_ACTION_END
            and metadata.get("sprint_id") == sprint_id
        ):
            return True
    return False


def _compute_block_message(smm_dir: Path, sprint_content: str) -> str | None:
    """Return the first triggered cascade block message, or None."""
    # Cascade step 1: accept gate
    if sprint_state.has_in_progress_stories(sprint_content):
        if markers.marker_exists(smm_dir, markers.ACCEPT):
            return _ACCEPT_MESSAGE
        return None

    # Cascade step 2: sprint-review gate — requires sprint complete
    if not sprint_state.is_sprint_complete(sprint_content):
        return None

    sprint_id = _sprint_id_from_content(sprint_content)
    if not sprint_id:
        # Can't match events without a sprint_id — don't block on malformed sprint.md
        return None

    events = _common.read_events_raw(smm_dir)
    if not _has_sprint_end_event(events, sprint_id):
        return _REVIEW_MESSAGE
    return None


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block message for the first triggered cascade step, or None."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    sprint_content = sprint_state.read_sprint_content(smm_dir)
    if sprint_content is None:
        return None

    block_message = _compute_block_message(smm_dir, sprint_content)
    if block_message is None:
        return None

    # Defer if mid-workflow — only pay the cost when we'd otherwise block
    agent_id = input_data.get("agent_id", "main")
    if _deferred(smm_dir, agent_id):
        return None

    return block_message


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Sprint lifecycle gate — action required.")
    sys.exit(0)
