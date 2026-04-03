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
import coordination
import markers


def _update_review_cycle_flags(smm_dir: Path, input_data: dict) -> None:
    """Set review cycle flags for review-related subagent completions.

    Runs even for xp- agents because we need to detect when
    xp-quality-review and simplify subagents complete.
    """
    agent_type = input_data.get("agent_type", "").lower()
    agent_id_val = input_data.get("agent_id", "").lower()

    flag: str | None = None
    if "simplify" in agent_type or "simplify" in agent_id_val:
        flag = "simplify_done"
    elif "quality-review" in agent_type or "quality-review" in agent_id_val:
        flag = "quality_review_done"

    if flag is not None:
        markers.set_review_flag(smm_dir, "main", flag)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core SubagentStop logic. Returns context or raises BlockedError."""
    # Review cycle flags must run before is_xp_agent skip because
    # xp-quality-review starts with "xp-" but still needs flag set.
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is not None:
        _update_review_cycle_flags(smm_dir, input_data)

    if _common.is_xp_agent(input_data):
        return None

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

    # Clear coordination entry and agent-scoped markers
    coordination.clear_coordination_agent(smm_dir, agent_id)
    markers.cleanup_agent_markers(smm_dir, agent_id)

    # Conflict detection — patterns 2-5 only (no file_path)
    events = _common.read_events_raw(smm_dir)
    concern_events = concerns.detect_conflicts(events, agent_id)
    for concern in concern_events:
        _common.append_safe(smm_dir, concern)

    # Plan review gate — Plan subagent (via Agent tool) also needs review.
    # PostToolUse:ExitPlanMode handles the EnterPlanMode/ExitPlanMode tool flow;
    # this handles the SubagentStop flow for Plan-type subagents.
    agent_type = input_data.get("agent_type", "")
    if agent_type == "Plan":
        markers.marker_write(smm_dir, markers.PLAN_AWAITING_REVIEW, agent_id)

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
