#!/usr/bin/env python3
"""Large-batch probe: nudge to commit when main agent piles up events.

When the main agent has emitted more than NUDGE_THRESHOLD events
since its last commit, append a status event suggesting an
intermediate green-state commit. Skips teammate sessions and avoids
duplicate nudges within a single batch window.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import identity

NUDGE_THRESHOLD = 40
NUDGE_AGENT_ID = "large-batch-probe"
NUDGE_CONTENT = "consider committing intermediate green state"


def _is_main_commit(event: dict) -> bool:
    return event.get("type") == _common.COMMIT and event.get("agent_id") == "main"


def _is_existing_nudge(event: dict) -> bool:
    return (
        event.get("type") == _common.STATUS and event.get("agent_id") == NUDGE_AGENT_ID
    )


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Append nudge + return text when main exceeds threshold post-commit.

    Returns NUDGE_CONTENT to be surfaced via PostToolUse additionalContext —
    the status event alone is invisible to the agent because prompt_nugget
    filters by type and excludes status. Returns None when guards trip,
    threshold isn't crossed, or a nudge already lives in the window.
    """
    if _common.is_xp_agent(input_data):
        return None
    if identity.resolve_agent_id(input_data) != "main":
        return None
    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_raw(smm_dir)
    main_event_count = 0
    nudge_already_in_window = False
    for i in range(len(events) - 1, -1, -1):
        e = events[i]
        if _is_main_commit(e):
            break
        if _is_existing_nudge(e):
            nudge_already_in_window = True
            continue
        if e.get("agent_id") == "main":
            main_event_count += 1

    if main_event_count <= NUDGE_THRESHOLD or nudge_already_in_window:
        return None

    nudge = _common.make_event(
        _common.STATUS,
        NUDGE_AGENT_ID,
        NUDGE_CONTENT,
        working_on=[],
    )
    _common.append_safe(smm_dir, nudge)
    return NUDGE_CONTENT


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("PostToolUse", result)
    sys.exit(0)
