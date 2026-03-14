#!/usr/bin/env python3
"""SubagentStart hook: inject SMM and set watermark for subagents.

Materializes the current SMM view, injects it as additionalContext,
and writes a watermark so the subagent's future delta reads start
from the current position.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import materialize

# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core subagent_start logic. Returns additionalContext string or None."""
    # Recursion prevention
    if _common.is_xp_agent(input_data):
        return None

    # Resolve SMM dir
    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "subagent")

    # Parse events once — used for both watermark count and rendering
    events, skipped = materialize.parse_events(smm_dir)
    if not events and skipped == 0:
        smm_content = ""
    else:
        indices = materialize.build_indices(events)
        conflicts = materialize.detect_conflicts(events, indices)
        smm_content = materialize.render_markdown(events, indices, conflicts, skipped)

    # Write watermark at current event count
    _common.write_watermark(smm_dir, agent_id, len(events))

    if smm_content:
        return _common.wrap_smm_context(smm_content)
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        _common.hook_output("SubagentStart", context)
    sys.exit(0)
