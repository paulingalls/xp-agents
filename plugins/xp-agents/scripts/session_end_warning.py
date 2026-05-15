#!/usr/bin/env python3
"""Stop command hook: session-end soft warning.

Surfaces unresolved concerns and reminds the agent to summarize
the session for the user. Soft warning only — does not block.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import read_delta

_WATERMARK_ID = "session-end-warning"


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return soft warning string if issues found, None otherwise."""
    if _common.is_xp_agent(input_data):
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = read_delta.read_delta_full(smm_dir, _WATERMARK_ID, update_watermark=False)[
        0
    ]
    if not events:
        return None

    parts: list[str] = []

    unresolved = _common.count_unresolved_concerns(events)
    if unresolved:
        parts.append(f"{unresolved} unresolved concern(s) — resolve before ending.")

    parts.append("Summarize this session's work for the user.")

    return "Session-end checklist: " + " ".join(parts)


if __name__ == "__main__":
    import json

    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        # Stop hooks don't support hookSpecificOutput/additionalContext.
        # Use top-level reason (soft warning, not a block).
        print(json.dumps({"reason": result}))
    sys.exit(0)
