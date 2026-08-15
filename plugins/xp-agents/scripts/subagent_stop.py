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
import append_validation
import assign_scope
import concerns
import coordination
import marker_names
import markers
import review_cycle_legs
import sprint_state
import sprint_status
import target_routing
from event_schema import (
    EVENT_TYPE_SPRINT,
    SPRINT_ACTION_END,
    STATUS_ACTION_HOUSEKEEPING_COMPLETE,
    STATUS_ACTION_PLAN_AWAITING_REVIEW,
    STATUS_ACTION_PLAN_COMPLETED,
    STATUS_ACTION_PLAN_REVIEWED,
    STATUS_ACTION_SUBAGENT_COMPLETE,
)

_WATERMARK_ID = "subagent-stop"

# Bare agent-type names. The hooks compare via `target_routing.strip_our_namespace`
# so both bare and `xp-agents:`-qualified forms route correctly without
# hand-enumerating the pair per slot.
_HOUSEKEEPER_BARE = "xp-housekeeper"
_SPRINT_REVIEWER_BARE = "xp-sprint-reviewer"
_PLAN_REVIEWER_BARE = "xp-plan-reviewer"
_PLAN_AGENT_TYPE = "Plan"
_HOUSEKEEPING_DONE_AGENT_ID = "xp-kickoff-done"
_SPRINT_REVIEWER_AGENT_ID = "xp-sprint-reviewer"
_PLAN_REVIEWER_AGENT_ID = "xp-plan-reviewer"


def _append_completion_event(
    smm_dir: Path, agent_id: str, agent_type: str, action: str
) -> None:
    event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_completed_content(agent_id),
        working_on=[],
        metadata={"action": action, "agent_type": agent_type},
    )
    _common.append_safe(smm_dir, event)


def _emit_subagent_complete(smm_dir: Path, input_data: dict) -> None:
    _append_completion_event(
        smm_dir,
        input_data.get("agent_id", "subagent"),
        input_data.get("agent_type", ""),
        STATUS_ACTION_SUBAGENT_COMPLETE,
    )


def _handle_housekeeping_done(smm_dir: Path, input_data: dict) -> None:
    """Handle xp-housekeeper completion: consume markers, log event, return None.

    On SubagentStop, returned additionalContext is delivered to the SUBAGENT
    and continues its turn — it does NOT reach the parent/main agent. So a
    SubagentStop handler must never use additionalContext to message the
    parent; main-agent messaging (e.g. process-guide injection) happens via
    PostToolUse:Skill|Agent in review_cycle_done.py.
    """
    agent_type = input_data.get("agent_type", "")
    if target_routing.strip_our_namespace(agent_type) != _HOUSEKEEPER_BARE:
        return None

    import housekeeping_flight

    # Retire the in-flight record whatever the outcome, then decide from what
    # it held whether this run actually curated.
    record = housekeeping_flight.consume(smm_dir, input_data)
    if not housekeeping_flight.finalized(smm_dir, record):
        # Leave NEEDS_HOUSEKEEPING armed so the gate blocks with its
        # never-invoked message and the lead starts a fresh housekeeper.
        failed = _common.make_event(
            _common.STATUS,
            _HOUSEKEEPING_DONE_AGENT_ID,
            "Housekeeper stopped but did not finalize curation — the curation "
            "watermark never moved. Housekeeping still needs to run.",
            working_on=[],
        )
        _common.append_safe(smm_dir, failed)
        return None

    markers.marker_consume(smm_dir, markers.KICKOFF)
    markers.marker_consume(smm_dir, markers.NEEDS_HOUSEKEEPING)

    status = _common.make_event(
        _common.STATUS,
        _HOUSEKEEPING_DONE_AGENT_ID,
        "Kickoff complete — housekeeping subagent finished.",
        working_on=[],
        metadata={"action": STATUS_ACTION_HOUSEKEEPING_COMPLETE},
    )
    _common.append_safe(smm_dir, status)

    _emit_subagent_complete(smm_dir, input_data)

    markers.marker_consume(smm_dir, markers.NEEDS_SPRINT)

    return None


def _handle_sprint_review_done(smm_dir: Path, input_data: dict) -> None:
    agent_type = input_data.get("agent_type", "")
    if target_routing.strip_our_namespace(agent_type) != _SPRINT_REVIEWER_BARE:
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

    _emit_subagent_complete(smm_dir, input_data)

    # Retire the record the Stop gate reads while the review runs — AFTER the
    # sprint_end append, since the record bridges the window where no
    # sprint_end exists yet and consuming first would briefly reopen it. A run
    # that dies before here leaves it to suppress the gate until it ages out.
    import sprint_review_flight

    sprint_review_flight.consume(smm_dir, input_data)

    for stale in smm_dir.glob(f"{marker_names.SPRINT_REVIEW_INPUT_PREFIX}*"):
        stale.unlink(missing_ok=True)

    return None


def _handle_close_reviewer_done(smm_dir: Path, input_data: dict) -> None:
    """Emit the close-reviewer's completion evidence, then consume CLOSE_CYCLE_ACTIVE.

    Must run BEFORE the is_xp_agent skip — close-reviewer is xp-*, would
    otherwise be silently skipped and leave the close-cycle gate blocking.

    The close-reviewer was the one subagent emitting NO completion event: it
    returned at the is_xp_agent skip before the generic _record_completion
    path. Emit the SAME subagent_complete evidence every other subagent
    produces (mirroring the sibling _handle_plan_review_done) so the
    close-cycle gate can cross-check reviewer-completion rather than trust the
    bare marker. Order is load-bearing: emit FIRST, consume SECOND — a crash
    between them must leave evidence, not a silently-consumed marker. The
    marker_consume stays: the marker is still the state teardown and
    abandonment backstop.
    """
    agent_type = input_data.get("agent_type", "")
    if (
        target_routing.strip_our_namespace(agent_type)
        != target_routing.CLOSE_REVIEWER_BARE
    ):
        return
    _emit_subagent_complete(smm_dir, input_data)
    markers.marker_consume(smm_dir, markers.CLOSE_CYCLE_ACTIVE)


def _handle_plan_review_done(smm_dir: Path, input_data: dict) -> None:
    """Record the plan reviewer's completion; arm the teammate assign gate.

    Returns None and emits NO continuing context. On SubagentStop, returned
    additionalContext is delivered to the SUBAGENT and continues its turn —
    so nudging /xp-assign here made the reviewer take one more turn reacting
    to the nudge, burying its four-block Final Message.
    The real teammate gate is the ASSIGN_PENDING marker on disk plus the
    plan_reviewed gate event, both written below; the reviewer's own
    Next-step block already tells the main agent to run /xp-assign.
    """
    agent_type = input_data.get("agent_type", "")
    if target_routing.strip_our_namespace(agent_type) != _PLAN_REVIEWER_BARE:
        return None

    # Narrow the assign gate to teammate-mode plans: only teammate mode
    # needs /xp-assign to create the branch and spawn the teammate (per
    # story). Solo/unset plan reviews leave no marker so the agent codes
    # straight through — but still record the reviewer's completion (the
    # generic path below skips xp-* agents).
    #
    # Loaded ONCE and read twice: the same sprint answers "is this a delegated
    # plan?" and "which stories is the marker being armed for?". The two used
    # to be separate loads of the same file.
    # A missing sprint collapses to the empty one: it has no promoted stories,
    # so it takes the same exit as a solo plan rather than needing its own.
    sprint_data = sprint_state.read_sprint_content(smm_dir) or {}
    promoted = sprint_status.select_promoted_teammate_stories(
        sprint_data.get("stories", [])
    )
    if not promoted:
        _emit_subagent_complete(smm_dir, input_data)
        return None

    agent_id = input_data.get("agent_id", _PLAN_REVIEWER_AGENT_ID)
    # SCOPE the marker to the stories this review covered, so a marker that
    # goes moot cannot gate an unrelated frontier promoted later. Only the
    # promoted set — deliberately NOT also filtered by "already spawned":
    # the reader applies that, and re-deriving it here would put a
    # `git worktree list` subprocess on the SubagentStop path. The simpler
    # form is also the safer one — a worktree that vanished while its story
    # is still in flight keeps the marker ARMED.
    markers.marker_write(
        smm_dir,
        markers.ASSIGN_PENDING,
        assign_scope.format_assign_scope(
            sprint_data.get("sprint_id") or "",
            [story.get("id", "") for story in promoted],
        ),
    )

    gate_event = _common.make_event(
        _common.STATUS,
        agent_id,
        "assign_pending: Plan reviewed, run /xp-assign",
        working_on=[],
        metadata={"action": STATUS_ACTION_PLAN_REVIEWED},
    )
    _common.append_safe(smm_dir, gate_event)

    _emit_subagent_complete(smm_dir, input_data)

    return None


def _record_completion(
    smm_dir: Path,
    agent_id: str,
    agent_type: str = "",
    action: str = STATUS_ACTION_SUBAGENT_COMPLETE,
) -> None:
    """Record subagent completion: status event + coordination + markers."""
    _append_completion_event(smm_dir, agent_id, agent_type, action)
    coordination.clear_coordination_agent(smm_dir, agent_id)
    markers.cleanup_agent_markers(smm_dir, agent_id)


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core SubagentStop logic. Always returns None.

    SubagentStop cannot deliver additionalContext to the main agent (the
    platform routes it back to the finished SUBAGENT instead), so this hook
    never returns continuing context — every handler records to the event log
    or writes a marker. Main-agent messaging happens via PostToolUse hooks.

    Review cycle flags + the four xp-* completion handlers run BEFORE the
    is_xp_agent skip — those agent_types start with "xp-" but still need
    their handlers to fire.
    """
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is not None:
        review_cycle_legs.update_review_cycle_flags(smm_dir, input_data)
        _handle_housekeeping_done(smm_dir, input_data)
        _handle_sprint_review_done(smm_dir, input_data)
        _handle_close_reviewer_done(smm_dir, input_data)
        _handle_plan_review_done(smm_dir, input_data)

    if _common.is_xp_agent(input_data):
        return None

    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "subagent")
    try:
        append_validation.validate_agent_id(agent_id)
    except ValueError:
        return None

    agent_type = input_data.get("agent_type", "")
    completion_action = (
        STATUS_ACTION_PLAN_COMPLETED
        if agent_type == _PLAN_AGENT_TYPE
        else STATUS_ACTION_SUBAGENT_COMPLETE
    )
    _record_completion(smm_dir, agent_id, agent_type, completion_action)

    events = _common.read_events_locked(smm_dir, _WATERMARK_ID)
    concern_events = concerns.detect_conflicts(events, agent_id)
    for concern in concern_events:
        _common.append_safe(smm_dir, concern)

    # Plan-via-Agent-tool flow; ExitPlanMode flow handled in PostToolUse:ExitPlanMode.
    if agent_type == _PLAN_AGENT_TYPE:
        markers.marker_write(smm_dir, markers.PLAN_AWAITING_REVIEW, agent_id)

        gate_event = _common.make_event(
            _common.STATUS,
            agent_id,
            "plan_awaiting_review: Plan completed, run /xp-review-plan",
            working_on=[],
            metadata={"action": STATUS_ACTION_PLAN_AWAITING_REVIEW},
        )
        _common.append_safe(smm_dir, gate_event)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
