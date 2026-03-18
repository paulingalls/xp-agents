#!/usr/bin/env python3
"""SubagentStart hook: inject SMM for subagents.

Reads the curated four-pillar SMM from disk (written by housekeeping).
Injects the SMM as additionalContext so subagents start with full
project context.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common

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

    # Read curated four-pillar SMM from disk (written by housekeeping)
    smm_file = smm_dir / "SHARED_MENTAL_MODEL.md"
    try:
        smm_content = smm_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        smm_content = ""

    # Record start event (pairs with "completed" in SubagentStop)
    start_event = _common.make_event(
        _common.STATUS,
        agent_id,
        _common.subagent_started_content(agent_id),
        working_on=[],
    )
    _common.append_safe(smm_dir, start_event)

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
