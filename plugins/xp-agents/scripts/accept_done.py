#!/usr/bin/env python3
"""PostToolUse:Skill hook: accept completion bookkeeping.

When /xp-accept completes, clears the 'needs acceptance' marker and
checks if the sprint is complete (all stories done/deferred). If
complete, nudges /xp-sprint-review.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers
import sprint_state

_ACCEPT_NAMES = {"xp-accept", "xp-agents:xp-accept"}

_SPRINT_COMPLETE_NUDGE = (
    "\n\n---\n**Sprint complete!** All stories are done or deferred. "
    "Run `/xp-sprint-review` to review the sprint."
)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Set accept marker and check sprint completion after /xp-accept."""
    if _common.is_xp_agent(input_data):
        return None

    tool_input = input_data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")
    if skill_name not in _ACCEPT_NAMES:
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Clear 'needs acceptance' marker
    markers.marker_consume(smm_dir, markers.ACCEPT)

    # Log iteration completion — countable by retrospective
    status = _common.make_event(
        _common.STATUS,
        "accept-done",
        "Iteration complete — accept verification done.",
        working_on=[],
        metadata={"action": "iteration_complete"},
    )
    _common.append_safe(smm_dir, status)

    # Check sprint completion
    sprint_content = sprint_state.read_sprint_content(smm_dir)
    if sprint_content and sprint_state.is_sprint_complete(sprint_content):
        return _SPRINT_COMPLETE_NUDGE

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
