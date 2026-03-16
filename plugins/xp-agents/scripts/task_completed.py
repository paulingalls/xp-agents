#!/usr/bin/env python3
"""TaskCompleted hook: nudge xp-quality-reviewer once per completed task.

Fires when a task is marked completed via TaskUpdate. Triggers one background
quality review per logical unit of work instead of after every file write.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

_NUDGE = (
    "Invoke the xp-quality-reviewer subagent in the background "
    "to review code changes made during this task."
)


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core TaskCompleted logic. Returns quality reviewer nudge or None."""
    if _common.is_xp_agent(input_data):
        return None
    return _NUDGE


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.hook_output("TaskCompleted", result)
    sys.exit(0)
