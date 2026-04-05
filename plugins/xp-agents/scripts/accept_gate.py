#!/usr/bin/env python3
"""Stop command hook: accept gate.

Blocks stop when sprint.md has in-progress stories and the accept
marker is present. The marker means "acceptance needed" — it is set
by pre_tool_write when code is written during an active sprint, and
cleared by accept_done when /xp-accept completes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import markers
import sprint_state

_BLOCK_REASON = (
    "Stories are in-progress. Run /xp-accept to verify "
    "acceptance criteria before stopping."
)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block reason if in-progress stories without accept, else None."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    sprint_content = sprint_state.read_sprint_content(smm_dir)
    if sprint_content is None or not sprint_state.has_in_progress_stories(
        sprint_content
    ):
        return None

    if not markers.marker_exists(smm_dir, markers.ACCEPT):
        return None

    # Defer if review cycle is actively in progress (at least one flag set)
    agent_id = input_data.get("agent_id", "main")
    cycle = markers.read_review_cycle(smm_dir, agent_id)
    review_flags = ("simplify_done", "quality_review_done", "security_review_done")
    if any(cycle.get(f) for f in review_flags):
        return None

    # Defer if teammates are active — main agent is coordinating, not stopping
    coord = coordination.read_coordination(smm_dir)
    if any(aid != agent_id for aid in coord):
        return None

    return _BLOCK_REASON


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Accept verification required — run /xp-accept.")
    sys.exit(0)
