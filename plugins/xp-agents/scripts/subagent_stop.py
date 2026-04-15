#!/usr/bin/env python3
"""SubagentStop hook: record subagent completion and run conflict detection.

Appends a minimal status event and checks for structural conflicts
(patterns 2-5, no file_path so pattern 1 is skipped).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import coordination
import markers
import smm_cli
import smm_store
import sprint_state
from event_schema import (
    EVENT_TYPE_SPRINT,
    SPRINT_ACTION_END,
)

_HOUSEKEEPER_AGENT_TYPES = {"xp-housekeeper", "xp-agents:xp-housekeeper"}
_SPRINT_REVIEWER_AGENT_TYPES = {"xp-sprint-reviewer", "xp-agents:xp-sprint-reviewer"}
_PLAN_REVIEWER_AGENT_TYPES = {"xp-plan-reviewer", "xp-agents:xp-plan-reviewer"}
_PLAN_AGENT_TYPE = "Plan"
_HOUSEKEEPING_DONE_AGENT_ID = "xp-kickoff-done"
_SPRINT_REVIEWER_AGENT_ID = "xp-sprint-reviewer"
_PLAN_REVIEWER_AGENT_ID = "xp-plan-reviewer"

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
    markers.marker_consume(smm_dir, markers.NEEDS_HOUSEKEEPING)

    # Compaction now runs inside smm_cli.save() so it covers both forked and
    # inline housekeeping paths — no need to do it here.
    status = _common.make_event(
        _common.STATUS,
        _HOUSEKEEPING_DONE_AGENT_ID,
        "Kickoff complete — housekeeping subagent finished.",
        working_on=[],
    )
    _common.append_safe(smm_dir, status)

    markers.marker_consume(smm_dir, markers.NEEDS_SPRINT)

    smm_data = smm_store.load_smm(smm_dir)
    smm_content = smm_cli.render_markdown(smm_data).strip()

    process = _common.load_process_guide()

    nudge = ""
    if not sprint_state.has_in_progress_stories(smm_dir):
        sprint_data = sprint_state.read_sprint_content(smm_dir)
        if sprint_data is not None:
            nudge = _SPRINT_NUDGE

    parts = [p for p in [smm_content, process, nudge] if p]
    return "\n\n".join(parts) if parts else None


def _handle_sprint_review_done(smm_dir: Path, input_data: dict) -> str | None:
    """Handle xp-sprint-reviewer subagent completion.

    Records a sprint end event with velocity and cleans up the review
    input file. Returns None — sprint sizing analysis runs at the
    start of the next session via retrospective.py.
    """
    agent_type = input_data.get("agent_type", "")
    if agent_type not in _SPRINT_REVIEWER_AGENT_TYPES:
        return None

    sprint_data = sprint_state.read_sprint_content(smm_dir)
    if sprint_data:
        from sprint_store import compute_velocity

        velocity = compute_velocity(sprint_data)
        sprint_id = sprint_data["sprint_id"] or "unknown"
        goal = sprint_data["goal"] or "Sprint review"

        event = _common.make_event(
            EVENT_TYPE_SPRINT,
            _SPRINT_REVIEWER_AGENT_ID,
            f"Sprint end: {goal}. "
            f"{velocity['stories_delivered']}/{velocity['stories_planned']}"
            " stories delivered.",
            metadata={
                "sprint_id": sprint_id,
                "action": SPRINT_ACTION_END,
                **velocity,
            },
        )
        _common.append_safe(smm_dir, event)

    (smm_dir / ".sprint-review-input.json").unlink(missing_ok=True)

    return None


def _handle_plan_review_done(smm_dir: Path, input_data: dict) -> str | None:
    """Handle xp-plan-reviewer completion — nudge /xp-assign.

    Sets .assign-pending marker and returns additionalContext telling
    the agent to run /xp-assign for execution mode selection.
    """
    agent_type = input_data.get("agent_type", "")
    if agent_type not in _PLAN_REVIEWER_AGENT_TYPES:
        return None

    agent_id = input_data.get("agent_id", _PLAN_REVIEWER_AGENT_ID)
    markers.marker_write(smm_dir, markers.ASSIGN_PENDING, agent_id)

    gate_event = _common.make_event(
        _common.STATUS,
        agent_id,
        "assign_pending: Plan reviewed, run /xp-assign",
        working_on=[],
    )
    _common.append_safe(smm_dir, gate_event)

    return (
        "IMPORTANT: Run the /xp-assign skill NOW to decide execution mode "
        "(solo vs worktree subagents). The skill analyzes the plan's steps "
        "and spawns teammates if parallel execution is appropriate."
    )


def _record_completion(smm_dir: Path, agent_id: str) -> None:
    """Record subagent completion: status event + coordination + markers."""
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_completed_content(agent_id),
        working_on=[],
    )
    _common.append_safe(smm_dir, event)
    coordination.clear_coordination_agent(smm_dir, agent_id)
    markers.cleanup_agent_markers(smm_dir, agent_id)


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

        # Sprint reviewer is also xp-* — its completion records sprint end.
        review_result = _handle_sprint_review_done(smm_dir, input_data)
        if review_result is not None:
            return review_result

        # Plan reviewer completion nudges /xp-assign for execution mode.
        assign_result = _handle_plan_review_done(smm_dir, input_data)
        if assign_result is not None:
            return assign_result

    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "subagent")
    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None

    _record_completion(smm_dir, agent_id)

    # Conflict detection — patterns 2-5 only (no file_path)
    events = _common.read_events_raw(smm_dir)
    concern_events = concerns.detect_conflicts(events, agent_id)
    for concern in concern_events:
        _common.append_safe(smm_dir, concern)

    # Plan review gate — Plan subagent (via Agent tool) also needs review.
    # PostToolUse:ExitPlanMode handles the EnterPlanMode/ExitPlanMode tool flow;
    # this handles the SubagentStop flow for Plan-type subagents.
    agent_type = input_data.get("agent_type", "")
    if agent_type == _PLAN_AGENT_TYPE:
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
