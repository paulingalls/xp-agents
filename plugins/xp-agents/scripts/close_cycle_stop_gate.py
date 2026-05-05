#!/usr/bin/env python3
"""Stop command hook: close-cycle gate.

Blocks Stop while a close skill is mid-cycle (CLOSE_CYCLE_ACTIVE marker
present), nudging the agent to invoke xp-close-reviewer next. The marker
is written by close skills before /security-review runs and consumed by
subagent_stop.py when xp-close-reviewer completes.

Defers on ASKING_USER so AskUserQuestion dialogues complete cleanly.
Review-cycle/teammates deferrals are intentionally NOT applied — the
close cycle wants to block mid-cycle by design.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers

_BLOCK_MESSAGE = (
    "Close cycle mid-flight. Run /security-review then invoke "
    "xp-close-reviewer (Agent tool); then continue Steps 5-7."
)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block message if close cycle is mid-flight, else None."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return None
    if markers.marker_exists(smm_dir, markers.CLOSE_CYCLE_ACTIVE):
        return _BLOCK_MESSAGE
    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Close cycle gate — close-reviewer pending.")
    sys.exit(0)
