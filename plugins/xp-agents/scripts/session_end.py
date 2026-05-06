#!/usr/bin/env python3
"""SessionEnd hook: record session summary to event log.

Computes duration, event count, unresolved items, active working_on,
and final status — then appends a session_end event.
"""

import bisect
import contextlib
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import _common
import concerns
import coordination
import identity
import markers
from event_builder import generate_id
from event_schema import (
    METADATA_KEY_FLAGGED_STALE,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_STALE_SESSION_COUNT,
    get_required_budget,
)

STALE_CONCERN_SESSION_THRESHOLD = 4

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _owns_goal(goal: dict, *, is_teammate: bool, agent_id: str) -> bool:
    """Return True if this session_end (running under agent_id) should
    take ownership of the goal event for resolution.

    Multi-teammate worktrees share one SMM. Goals from worktree-story-*
    agents belong to that specific teammate; everything else
    (xp-kickoff, xp-work-selection, main) belongs to the main session.
    """
    goal_agent = goal.get("agent_id", "")
    if identity.is_teammate_agent_id(goal_agent):
        return is_teammate and goal_agent == agent_id
    return not is_teammate


def _compute_summary(
    events: list[dict],
    resolutions: dict,
    *,
    owns_goal,
) -> dict:
    """Compute session summary from events.

    `owns_goal(event) -> bool` decides which goal events this session_end
    takes responsibility for resolving (cross-teammate isolation).
    """
    session_start_idx = _common.current_session_start_index(events)

    # Single pass over events: collect questions, concerns, status-by-agent,
    # and goal IDs this session owns. Goals are not bounded to the current
    # session window — once a goal is owned and unresolved, this session_end
    # resolves it (lets compaction clean up backlog from earlier sessions
    # that ran before this fix shipped).
    resolved_goal_ids = resolutions["resolved_goal_ids"]
    question_ids: set[str] = set()
    concern_ids: set[str] = set()
    session_goal_ids: list[str] = []
    latest_status: dict[str, dict] = {}
    for e in events:
        eid = e.get("id", "")
        match e.get("type"):
            case _common.QUESTION if eid:
                question_ids.add(eid)
            case _common.CONCERN if eid:
                concern_ids.add(eid)
            case _common.STATUS:
                latest_status[e.get("agent_id", "")] = e
            case _common.GOAL if eid and eid not in resolved_goal_ids and owns_goal(e):
                session_goal_ids.append(eid)

    duration_seconds: float = 0
    now = datetime.now(timezone.utc)
    if session_start_idx < len(events):
        first_ts = events[session_start_idx].get("ts", "")
        if first_ts:
            try:
                first_dt = datetime.fromisoformat(first_ts)
                duration_seconds = (now - first_dt).total_seconds()
            except (ValueError, TypeError):
                pass

    unresolved = sorted(
        (question_ids - resolutions["answered_question_ids"])
        | (concern_ids - resolutions["resolved_concern_ids"])
    )

    all_working_on: list[str] = []
    for agent_id in sorted(latest_status):
        files = latest_status[agent_id].get("working_on", [])
        all_working_on.extend(files)

    return {
        "duration_seconds": duration_seconds,
        "event_count": len(events),
        "unresolved_items": unresolved,
        "working_on": all_working_on,
        "resolved_goal_ids": sorted(session_goal_ids),
    }


def _sweep_stale_concerns(
    smm_dir: Path,
    events: list[dict],
    resolutions: dict,
    agent_id: str,
) -> None:
    """Emit one flag-concern per open concern that has survived
    STALE_CONCERN_SESSION_THRESHOLD or more SESSION_END markers.

    Idempotency: a concern that already has an unresolved flag-concern
    pointing back to it (metadata.flagged_stale=True, references=[orig_id])
    is skipped to prevent every session_end from appending another flag.
    """
    resolved_ids = resolutions["resolved_concern_ids"]
    already_flagged: set[str] = set()
    session_end_positions: list[int] = []
    concern_position: dict[str, int] = {}
    for i, e in enumerate(events):
        match e.get("type"):
            case _common.SESSION_END:
                session_end_positions.append(i)
            case _common.CONCERN:
                eid = e.get("id", "")
                if eid:
                    concern_position[eid] = i
                if (
                    eid not in resolved_ids
                    and (e.get("metadata") or {}).get("flagged_stale") is True
                ):
                    already_flagged.update(e.get("references") or [])
    stale = concerns.filter_by_session_age(
        events,
        STALE_CONCERN_SESSION_THRESHOLD,
        resolutions=resolutions,
        session_end_positions=session_end_positions,
    )
    if not stale:
        return
    total_ends = len(session_end_positions)
    flag_events: list[dict] = []
    for orig in stale:
        orig_id = orig.get("id", "")
        if not orig_id or orig_id in already_flagged:
            continue
        ends_since = total_ends - bisect.bisect_right(
            session_end_positions, concern_position[orig_id]
        )
        flag_events.append(
            concerns.make_concern(
                content=(
                    f"Concern {orig_id} is stale ({ends_since} sessions old)"
                    " — triage at next kickoff"
                ),
                severity="low",
                agent_id=agent_id,
                references=[orig_id],
                metadata={
                    METADATA_KEY_FLAGGED_STALE: True,
                    METADATA_KEY_STALE_SESSION_COUNT: ends_since,
                },
            )
        )
    if flag_events:
        _common.bulk_append_safe(smm_dir, flag_events)


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core session_end logic. Appends session_end event."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    # Resolve SMM dir
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Read events and compute summary
    events, resolutions = _common.load_events_with_resolutions(smm_dir)
    agent_id = identity.resolve_agent_id(input_data)
    is_teammate = identity.is_worktree_teammate(input_data)
    summary = _compute_summary(
        events,
        resolutions,
        owns_goal=lambda g: _owns_goal(g, is_teammate=is_teammate, agent_id=agent_id),
    )

    _sweep_stale_concerns(smm_dir, events, resolutions, agent_id)

    # Build session_end event directly (avoids subprocess + shell escaping)
    prefix = "Session ended: "
    budget = get_required_budget(_common.SESSION_END)
    max_reason = budget - len(prefix)
    reason = input_data.get("reason", "unknown")[:max_reason]
    event = {
        "id": generate_id(),
        "ts": _common.now_iso(),
        "type": _common.SESSION_END,
        "agent_id": agent_id,
        "content": f"{prefix}{reason}",
        "schema_version": 1,
        "duration_seconds": summary["duration_seconds"],
        "event_count": summary["event_count"],
        "unresolved_items": summary["unresolved_items"],
        "working_on": summary["working_on"],
    }
    if summary["resolved_goal_ids"]:
        event["metadata"] = {METADATA_KEY_RESOLVES: summary["resolved_goal_ids"]}

    # Validate
    errors = _append_impl.validate_event(event)
    if errors:
        for err in errors:
            print(f"session_end validation error: {err}", file=sys.stderr)
        return None

    # Append
    try:
        _append_impl.append_event(smm_dir, event)
    except _append_impl.LockTimeoutError as e:
        print(f"session_end lock error: {e}", file=sys.stderr)

    if is_teammate:
        branch = identity.get_current_branch(input_data.get("cwd", ".")) or "unknown"
        completion = {
            "id": generate_id(),
            "ts": _common.now_iso(),
            "type": _common.STATUS,
            "agent_id": agent_id,
            "content": f"Teammate {agent_id} completed on branch {branch}",
            "schema_version": 1,
            "working_on": [],
            "metadata": {"branch": branch},
        }
        with contextlib.suppress(_append_impl.LockTimeoutError):
            _append_impl.append_event(smm_dir, completion)

    # Clear agent's coordination entry and agent-scoped markers
    coordination.clear_coordination_agent(smm_dir, agent_id)
    markers.cleanup_agent_markers(smm_dir, agent_id)

    # Clear session-scoped flags so they re-fire next session
    with contextlib.suppress(OSError):
        (smm_dir / ".lint-warned").unlink()

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
