#!/usr/bin/env python3
"""PostToolUse hook for ExitPlanMode: nudge plan review and write marker.

After the agent exits plan mode, inject context telling it to run
/xp-review-plan before implementing. Also writes the .plan-awaiting-review
marker so pre_tool_write.py can nudge on writes if the agent ignores this.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import identity
import markers


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Nudge plan review after ExitPlanMode."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = identity.resolve_agent_id(input_data)

    # Capture plan file path from ExitPlanMode response
    tool_response = input_data.get("tool_response", {})
    if isinstance(tool_response, str):
        plan_path = ""
    else:
        plan_path = tool_response.get("planFilePath", "")

    # Write marker with plan path so the review preload can include the plan
    markers.marker_write(smm_dir, markers.PLAN_AWAITING_REVIEW, plan_path or agent_id)

    # Record event for SMM history
    gate_event = _common.make_event(
        _common.STATUS,
        agent_id,
        "plan_awaiting_review: Plan completed, run /xp-review-plan",
        working_on=[],
    )
    _common.append_safe(smm_dir, gate_event)

    return (
        "IMPORTANT: Run the /xp-review-plan skill NOW before writing any code. "
        "The plan must be reviewed for XP compliance (TDD order, scope, risks) "
        "before implementation begins. Show the full review output to the user."
    )


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
