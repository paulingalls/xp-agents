#!/usr/bin/env python3
"""PostToolUse command hook: auto-status, conflict detection, semantic enrichment.

Fires after Write/Edit/MultiEdit. Records what happened, detects structural
conflicts (log-only, never blocks), and enriches status with semantic references.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import append_validation
import concerns
import coordination
import event_schema
import hook_liveness
import identity
import worktree

_WATERMARK_ID = "post-tool-use"

# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core PostToolUse logic. Appends events, returns quality nudge context."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    # Ahead of the file-path / agent-id early returns below: the write
    # records that this hook RAN, which holds even for a tool call this
    # hook otherwise has nothing to log. Guarded for free by the
    # is_xp_agent return above, which already sits ahead of this line.
    hook_liveness.write_heartbeat(
        smm_dir, session_id=hook_liveness.payload_session_id(input_data)
    )

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    agent_id = identity.resolve_agent_id(input_data)
    try:
        append_validation.validate_agent_id(agent_id)
    except ValueError:
        return None
    cwd = input_data.get("cwd", ".")

    file_path = _common.extract_file_path(tool_name, tool_input)
    if not file_path:
        return None

    normalized = worktree.normalize_path(file_path, cwd)

    events = _common.read_events_locked(smm_dir, _WATERMARK_ID)

    # Semantic references
    refs = concerns.find_related_decisions(events, file_path, cwd)

    # Auto-status event. metadata.action+files are the canonical structured
    # signal per the deterministic-event vocabulary; content is dual-emitted
    # as a digest.
    extra: dict = {
        "working_on": [normalized],
        "metadata": {
            "action": event_schema.STATUS_ACTION_FILE_WRITE,
            "files": [normalized],
        },
    }
    if refs:
        extra["references"] = refs
    status_event = _common.make_event(
        _common.STATUS,
        agent_id,
        f"Wrote to {normalized}",
        **extra,
    )
    _common.append_safe(smm_dir, status_event)

    # Update coordination file for real-time conflict detection
    coordination.update_coordination(smm_dir, agent_id, [normalized])

    # Conflict detection — log-only, never exit 2
    concern_events = concerns.detect_conflicts(
        events, agent_id, file_path=file_path, cwd=cwd
    )
    for concern in concern_events:
        _common.append_safe(smm_dir, concern)

    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    run(_common.read_hook_input())
    sys.exit(0)
