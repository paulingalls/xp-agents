#!/usr/bin/env python3
"""SessionEnd hook: record session summary to event log.

Computes duration, event count, unresolved items, active working_on,
and final status — then appends a session_end event.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _append_impl
import _common
import coordination
import resolution

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _compute_summary(events: list[dict]) -> dict:
    """Compute session summary from events."""
    event_count = len(events)

    # Duration: time from first event after last session_end to now
    # Find the start of the current session
    session_start_idx = 0
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("type") == _common.SESSION_END:
            session_start_idx = i + 1
            break

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

    # Unresolved: questions with no answer, concerns with no resolution
    question_ids = {
        e["id"] for e in events if e.get("type") == _common.QUESTION and e.get("id")
    }
    concern_ids = {
        e["id"] for e in events if e.get("type") == _common.CONCERN and e.get("id")
    }

    resolutions = resolution.compute_resolutions(events)
    unresolved = sorted(
        (question_ids - resolutions["answered_question_ids"])
        | (concern_ids - resolutions["resolved_concern_ids"])
    )

    # Active working_on: latest status per agent
    latest_status: dict[str, dict] = {}
    for e in events:
        if e.get("type") == _common.STATUS:
            latest_status[e.get("agent_id", "")] = e

    all_working_on: list[str] = []
    for agent_id in sorted(latest_status):
        files = latest_status[agent_id].get("working_on", [])
        all_working_on.extend(files)

    # Final status: is the last event from "main" agent a status?
    final_status_recorded = False
    for e in reversed(events):
        if e.get("agent_id") == "main":
            final_status_recorded = e.get("type") == _common.STATUS
            break

    return {
        "duration_seconds": duration_seconds,
        "event_count": event_count,
        "unresolved_items": unresolved,
        "working_on": all_working_on,
        "final_status_recorded": final_status_recorded,
    }


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Core session_end logic. Appends session_end event."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    # Resolve SMM dir
    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Read events and compute summary
    events = _common.read_events_raw(smm_dir)
    summary = _compute_summary(events)

    # Build session_end event directly (avoids subprocess + shell escaping)
    event = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": _common.SESSION_END,
        "agent_id": "main",
        "content": f"Session ended: {input_data.get('reason', 'unknown')}",
        "schema_version": 1,
        "duration_seconds": summary["duration_seconds"],
        "event_count": summary["event_count"],
        "unresolved_items": summary["unresolved_items"],
        "working_on": summary["working_on"],
        "final_status_recorded": summary["final_status_recorded"],
    }

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

    # Clear agent's coordination entry
    agent_id = input_data.get("agent_id", "main")
    coordination.clear_coordination_agent(smm_dir, agent_id)

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
