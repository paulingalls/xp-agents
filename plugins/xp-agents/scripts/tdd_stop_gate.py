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
import identity
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

    # Bound once and shared with every reader below. Two independently-written
    # spellings of the reader's cwd is the same defect shape as the agent-id
    # disagreement this gate was fixed for.
    cwd = input_data.get("cwd", ".")

    signal = tdd_check.find_last_test_signal(events, cwd, smm_dir)
    if signal == "fail":
        # RESOLVED, never the raw payload field. The harness sends `agent_id`
        # only when a hook fires inside a subagent call, and Stop fires on the
        # main thread — so the raw read was always `""`, nothing in
        # coordination equals `""`, and `has_active_teammates` answered yes
        # against every entry. `post_tool_use` writes one on every file write
        # with a 30-minute TTL, so this gate released unconditionally.
        #
        # `resolve_agent_id` specifically, not a richer resolution: it is the
        # same function `post_tool_use` uses to WRITE the coordination key
        # being compared against, and a reader that does not share the writer's
        # key space cannot answer this question at all.
        agent_id = identity.resolve_agent_id(input_data)
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
