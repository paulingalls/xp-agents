#!/usr/bin/env python3
"""SessionEnd hook: record session summary to event log.

Computes duration, event count, unresolved items, active working_on,
and final status — then appends a session_end event (main only).

Session-boundary *side-effects* (the stale-concern sweep and prior-session
goal-resolution) re-home to the SessionStart hook in Milestone 3 (story-002),
because SessionEnd misfires (/exit emits none; each worktree teammate emits
its own). Teammates therefore emit only a completion status here, never a
session_end event — a per-teammate session_end would corrupt boundary counts.
"""

import contextlib
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import _common
import coordination
import identity
import marker_names
import markers
from event_builder import generate_id
from event_schema import get_required_budget

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _compute_summary(events: list[dict], resolutions: dict) -> dict:
    """Compute session summary from events (main session_end only)."""
    session_start_idx = _common.current_session_start_index(events)

    # Single pass: collect question/concern ids and latest status per agent.
    question_ids: set[str] = set()
    concern_ids: set[str] = set()
    latest_status: dict[str, dict] = {}
    for e in events:
        eid = e.get("id", "")
        match e.get("type"):
            case _common.QUESTION if eid:
                question_ids.add(eid)
            case _common.CONCERN if eid:
                concern_ids.add(eid)
            case _common.STATUS:
                aid = e.get("agent_id", "")
                # Same `xp-` fence the conflict detector and the subagent
                # dispatcher apply to this map. A plugin subagent's claim is
                # scoped to the run that spawned it and is never cleared, so
                # counting it here reports the files a long-finished planning
                # or sprint-start subagent touched as still in flight, in every
                # session summary from now on.
                if not _common.is_xp_agent_id(aid):
                    latest_status[aid] = e

    # Duration spans from the current session's start to now. The anchor is
    # the most recent SESSION_STARTED event (current_session_start_index);
    # with no anchor it falls back to a tail cap, so a resume/compact
    # continuation measures from the original fresh start.
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
    }


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core session_end logic. Appends a session_end event on main; a
    worktree teammate appends only a completion status."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    # Resolve SMM dir
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events, resolutions = _common.load_events_with_resolutions(smm_dir)
    agent_id = identity.resolve_agent_id(input_data)
    is_teammate = identity.is_worktree_teammate(input_data)

    if is_teammate:
        # Teammates share main's session window with no anchor of their own,
        # so they emit no session_end — only a completion status.
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
    else:
        summary = _compute_summary(events, resolutions)
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
        errors = _append_impl.validate_event(event)
        if errors:
            for err in errors:
                print(f"session_end validation error: {err}", file=sys.stderr)
            return None
        try:
            _append_impl.append_event(smm_dir, event)
        except _append_impl.LockTimeoutError as e:
            print(f"session_end lock error: {e}", file=sys.stderr)

    # Clear agent's coordination entry and agent-scoped markers
    coordination.clear_coordination_agent(smm_dir, agent_id)
    markers.cleanup_agent_markers(smm_dir, agent_id)

    # Clear session-scoped flags so they re-fire next session
    with contextlib.suppress(OSError):
        (smm_dir / marker_names.LINT_WARNED).unlink()

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
