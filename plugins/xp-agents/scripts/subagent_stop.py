#!/usr/bin/env python3
"""SubagentStop hook: record subagent completion and run conflict detection.

Appends a minimal status event and checks for structural conflicts
(patterns 2-5, no file_path so pattern 1 is skipped).
"""

import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import compact
import concerns
import coordination
import markers
import sprint_state

_HOUSEKEEPER_AGENT_TYPES = {"xp-housekeeper", "xp-agents:xp-housekeeper"}
_HOUSEKEEPING_DONE_AGENT_ID = "xp-kickoff-done"

_SPRINT_NUDGE = (
    "\n\n---\n**Sprint notice:** No stories marked "
    "`in-progress`. Run story selection to pick "
    "stories for this iteration."
)


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


def _handle_housekeeping_done(smm_dir: Path, input_data: dict) -> str | None:
    """Handle xp-housekeeper subagent completion.

    Consumes markers, compacts the event log, logs a kickoff-done status,
    and returns the SMM + process guide as additionalContext. Also appends
    a sprint nudge if no stories are currently in-progress.

    Returns the context string or None if this isn't the housekeeper agent.
    """
    agent_type = input_data.get("agent_type", "")
    if agent_type not in _HOUSEKEEPER_AGENT_TYPES:
        return None

    markers.marker_consume(smm_dir, markers.KICKOFF)

    compact_result = None
    try:
        compact_result = compact.compact_after_curation(smm_dir)
    except Exception as e:
        concern = _common.make_event(
            _common.CONCERN,
            _HOUSEKEEPING_DONE_AGENT_ID,
            f"Event log compaction failed: {e}",
            severity="low",
        )
        _common.append_safe(smm_dir, concern)

    archived = compact_result["archived"] if compact_result else 0
    retained = compact_result["retained"] if compact_result else 0
    status = _common.make_event(
        _common.STATUS,
        _HOUSEKEEPING_DONE_AGENT_ID,
        f"Kickoff complete. Compacted: {archived} archived, {retained} retained.",
        working_on=[],
    )
    _common.append_safe(smm_dir, status)

    # Legacy marker cleanup — proper clearing moves to save_product_spec.py
    # and save_sprint.py in subsequent commits.
    markers.marker_consume(smm_dir, markers.NEEDS_PRODUCT_SPEC)
    markers.marker_consume(smm_dir, markers.NEEDS_SPRINT)

    smm_content = ""
    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
    with contextlib.suppress(FileNotFoundError):
        smm_content = smm_file.read_text(encoding="utf-8").strip()

    process = _common.load_process_guide()

    sprint_content = sprint_state.read_sprint_content(smm_dir)
    nudge = ""
    if sprint_content and not sprint_state.has_in_progress_stories(sprint_content):
        nudge = _SPRINT_NUDGE

    parts = [p for p in [smm_content, process, nudge] if p]
    return "\n\n".join(parts) if parts else None


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core SubagentStop logic. Returns context or None."""
    # Review cycle flags must run before is_xp_agent skip because
    # xp-quality-review starts with "xp-" but still needs flag set.
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is not None:
        _update_review_cycle_flags(smm_dir, input_data)

        # Housekeeper is an xp-* agent but we need its completion signal
        # to inject the curated SMM back to the main agent.
        housekeeping_result = _handle_housekeeping_done(smm_dir, input_data)
        if housekeeping_result is not None:
            return housekeeping_result

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
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("SubagentStop", result)
    sys.exit(0)
