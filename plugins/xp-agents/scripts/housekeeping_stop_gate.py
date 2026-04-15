#!/usr/bin/env python3
"""Stop command hook: block session end until housekeeping has run.

Set by kickoff_gate when .needs-kickoff is consumed. Cleared by
subagent_stop when the housekeeper subagent completes. Defers when
ASKING_USER is set so "Chat about this..." on AskUserQuestion works.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import markers

_BLOCK_MESSAGE = "Housekeeping hasn't run yet. Run /xp-housekeeping before ending."


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block message if .needs-housekeeping is set, else None."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    if not markers.marker_exists(smm_dir, markers.NEEDS_HOUSEKEEPING):
        return None

    if markers.marker_exists(smm_dir, markers.ASKING_USER):
        return None

    return _BLOCK_MESSAGE


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Housekeeping gate — action required.")
    sys.exit(0)
