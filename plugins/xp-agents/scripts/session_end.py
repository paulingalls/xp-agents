#!/usr/bin/env python3
"""SessionEnd hook: record session summary to event log.

Computes duration, event count, unresolved items, active working_on,
and final status — then appends a session_end event.
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
import markers
from event_builder import generate_id
from event_schema import CONTENT_BUDGETS, METADATA_KEY_RESOLVES

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _compute_summary(events: list[dict], resolutions: dict) -> dict:
    """Compute session summary from events."""
    session_start_idx = _common.current_session_start_index(events)

    # Single pass over events: collect questions, concerns, status-by-agent,
    # and current-session goal IDs. Goals are session-scoped (emitted by
    # /xp-kickoff and /xp-work-selection); resolving them on the session_end
    # event lets compaction archive them instead of letting them accumulate.
    question_ids: set[str] = set()
    concern_ids: set[str] = set()
    session_goal_ids: list[str] = []
    latest_status: dict[str, dict] = {}
    for i, e in enumerate(events):
        eid = e.get("id", "")
        match e.get("type"):
            case _common.QUESTION if eid:
                question_ids.add(eid)
            case _common.CONCERN if eid:
                concern_ids.add(eid)
            case _common.STATUS:
                latest_status[e.get("agent_id", "")] = e
            case _common.GOAL if eid and i >= session_start_idx:
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
    summary = _compute_summary(events, resolutions)

    agent_id = identity.resolve_agent_id(input_data)

    # Build session_end event directly (avoids subprocess + shell escaping)
    prefix = "Session ended: "
    budget = CONTENT_BUDGETS[_common.SESSION_END]
    assert budget is not None
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

    if identity.is_worktree_teammate(input_data):
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
