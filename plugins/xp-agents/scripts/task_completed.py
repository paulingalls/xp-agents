#!/usr/bin/env python3
"""TaskCompleted hook: gate navigator guidance.

Blocks task completion unless navigator guidance has been provided
(pair_guidance event exists since last task completion). On second
attempt for the same task, allows through to prevent infinite loops.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

_NAV_BLOCK_MSG = (
    "Run /xp-navigator to review your work before completing this task. "
    "The navigator checks alignment with decisions, conventions, and debt."
)


def _has_recent_guidance(events: list[dict]) -> bool:
    """Check if pair_guidance exists since the last task_completed gate."""
    # Walk backwards — if we find pair_guidance before a previous
    # navigator gate block, guidance was provided for this work unit
    for e in reversed(events):
        etype = e.get("type", "")
        if etype == _common.PAIR_GUIDANCE:
            return True
        # If we hit a previous task completion, stop looking —
        # guidance must be for the CURRENT work unit
        if etype == "status" and "task_completed_gate" in e.get("content", ""):
            return False
    return False


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core TaskCompleted logic.

    Returns additionalContext string, or raises BlockedError.
    Returns None to skip silently (xp agents, missing SMM).
    """
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    enforcement = _common.load_enforcement_mode()
    events = _common.read_events_raw(smm_dir)

    if not _has_recent_guidance(events):
        already_blocked = any(
            e.get("type") == "status"
            and "task_completed_gate" in e.get("content", "")
            and e.get("agent_id") == input_data.get("agent_id", "main")
            for e in reversed(events[-20:])  # only check recent
        )

        if already_blocked:
            # Second attempt — allow through
            return None

        # First attempt — record gate event and block
        agent_id = input_data.get("agent_id", "main")
        event = _common.make_event(
            "status",
            agent_id,
            "task_completed_gate: navigator guidance required",
            working_on=[],
        )
        _common.append_safe(smm_dir, event)

        if enforcement == _common.ENFORCEMENT_ADVISORY:
            return f"⚠️ Advisory: {_NAV_BLOCK_MSG}"

        raise _common.BlockedError(_NAV_BLOCK_MSG)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    try:
        result = run(input_data)
    except _common.BlockedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    if result:
        _common.hook_output("TaskCompleted", result)
    sys.exit(0)
