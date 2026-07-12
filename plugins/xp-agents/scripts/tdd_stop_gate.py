#!/usr/bin/env python3
"""Stop command hook: TDD gate.

Blocks stop when the most recent test run in the event log failed.
Replaces the tdd_check.md prompt hook with deterministic event parsing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import coordination
import tdd_check

_WATERMARK_ID = "tdd-stop-gate"


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block reason if tests failing, None otherwise."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    if not events:
        return None

    signal = tdd_check.find_last_test_signal(events, input_data.get("cwd", "."))
    if signal == "fail":
        agent_id = input_data.get("agent_id", "")
        if coordination.has_active_teammates(smm_dir, agent_id):
            return None  # Teammates may own the failing tests
        return "Tests are failing. Fix failing tests before stopping."

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Test failures detected — fix before stopping.")
    sys.exit(0)
