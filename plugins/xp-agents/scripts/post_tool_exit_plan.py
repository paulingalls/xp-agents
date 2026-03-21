#!/usr/bin/env python3
"""PostToolUse hook for ExitPlanMode: nudge plan review and write marker.

After the agent exits plan mode, inject context telling it to run
/xp-review-plan before implementing. Also writes the .plan-awaiting-review
marker so pre_tool_write.py can nudge on writes if the agent ignores this.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Nudge plan review after ExitPlanMode."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "main")

    # Write marker for pre_tool_write.py backup nudge
    marker = smm_dir / ".plan-awaiting-review"
    marker.write_text(agent_id)

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
        "before implementation begins."
    )


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": result,
            }
        }
        print(json.dumps(output))
    sys.exit(0)
