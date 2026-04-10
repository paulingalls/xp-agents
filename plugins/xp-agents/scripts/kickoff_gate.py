#!/usr/bin/env python3
"""UserPromptSubmit hook: gate on .needs-kickoff marker.

Blocks user prompts until /xp-kickoff has been run. Allows
the kickoff command itself through. Respects enforcement mode.

Behavior depends on marker content:
- "startup" (new session): hard block
- "clear" (mid-session reset): nudge only (work may be in progress)

Task-notifications from background agents are always skipped.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers

_NUDGE = "nudge"

_REVIEW_MESSAGE = (
    "Session kickoff required. Run /xp-kickoff to review "
    "open goals, concerns, decisions, and debt before proceeding."
)


def run(input_data: dict, smm_dir: Path | None = None) -> dict | str | None:
    """Check marker and block/nudge if kickoff needed.

    Returns a decision dict, a nudge string, or None.
    """
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if not markers.marker_exists(smm_dir, markers.KICKOFF):
        return None

    prompt = input_data.get("prompt", "")

    # Skip task-notifications — background agent completions aren't user prompts
    if _common.is_task_notification(prompt):
        return None

    if "/xp-kickoff" in prompt:
        # Clear marker now — kickoff is running, so sub-skills (goal collection,
        # question triage) can use AskUserQuestion without hitting this gate.
        markers.marker_consume(smm_dir, markers.KICKOFF)
        return None

    # Read marker content to determine block vs nudge.
    # "clear" = mid-session reset, nudge only.
    # "startup" or empty = new session, hard block.
    source = markers.marker_read(smm_dir, markers.KICKOFF) or ""

    if source == "clear":
        return _NUDGE

    reason = _REVIEW_MESSAGE
    extras: list[str] = []
    if markers.marker_exists(smm_dir, markers.NEEDS_EXECUTION_PLAN):
        extras.append("Run /xp-plan to create an execution plan.")
    if markers.marker_exists(smm_dir, markers.NEEDS_SPRINT):
        extras.append("Run /xp-sprint-start to plan sprint stories.")
    if extras:
        reason = reason + " " + " ".join(extras)

    return {
        "decision": "block",
        "reason": reason,
    }


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result == _NUDGE:
        _common.hook_output("UserPromptSubmit", _REVIEW_MESSAGE)
    elif isinstance(result, dict):
        result["systemMessage"] = "Session kickoff required — run /xp-kickoff."
        print(json.dumps(result))
    sys.exit(0)
