#!/usr/bin/env python3
"""PreToolUse hook for EnterPlanMode: the schedule plan-mode gate.

Blocks entering plan mode in the schedule trigger window (scheduled stories
exist, none in-progress) so /xp-schedule sets the planning scope first — solo
plans one story; teammate plans the batch so /xp-assign can split it. Without
this, the agent can plan the wrong unit before deciding mode.

State-derived (no marker to rm past): the only legitimate exit is /xp-schedule
promoting a frontier scheduled->in-progress, which self-clears the gate. Free
mode / no sprint / a fully-promoted sprint never fire.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import sprint_status


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Pure gate: returns None to allow, raises BlockedError to block."""
    if _common.is_xp_agent(input_data):
        return

    smm_dir = _common.get_validated_smm_dir(smm_dir)

    if smm_dir and sprint_status.schedule_gate_active(smm_dir):
        raise _common.BlockedError(
            "Run /xp-schedule to promote the next frontier and pick solo/"
            "teammate before entering plan mode — it sets the planning scope.",
            "Schedule the next frontier before planning.",
        )


if __name__ == "__main__":
    input_data = _common.read_hook_input()

    try:
        run(input_data)
    except _common.BlockedError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
