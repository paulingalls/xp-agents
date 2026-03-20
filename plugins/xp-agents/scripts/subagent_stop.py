#!/usr/bin/env python3
"""SubagentStop hook: record subagent completion and run conflict detection.

Appends a minimal status event and checks for structural conflicts
(patterns 2-5, no file_path so pattern 1 is skipped).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import concerns


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core SubagentStop logic. Returns context or raises BlockedError."""
    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "subagent")
    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None

    # Minimal completion status
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_completed_content(agent_id),
        working_on=[],
    )
    _common.append_safe(smm_dir, event)

    # Conflict detection — patterns 2-5 only (no file_path)
    events = _common.read_events_raw(smm_dir)
    concern_events = concerns.detect_conflicts(events, agent_id)
    for concern in concern_events:
        _common.append_safe(smm_dir, concern)

    # Plan review gate — write marker event for PreToolUse to detect.
    # Don't block (causes re-planning loops) or nudge via reason (silently dropped).
    agent_type = input_data.get("agent_type", "")
    if agent_type == "Plan":
        # Write marker file for O(1) check in pre_tool_write.py
        marker = smm_dir / ".plan-awaiting-review"
        marker.write_text(agent_id)

        # Keep the event for SMM history
        gate_event = _common.make_event(
            _common.STATUS,
            agent_id,
            "plan_awaiting_review: Plan completed, run /xp-review-plan",
            working_on=[],
        )
        _common.append_safe(smm_dir, gate_event)

    return None


if __name__ == "__main__":
    run(_common.read_hook_input())
    sys.exit(0)
