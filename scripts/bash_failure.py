#!/usr/bin/env python3
"""PostToolUseFailure command hook for Bash: capture failed test runs.

PostToolUse only fires on success. When a Bash command exits non-zero
(e.g., test suite fails), PostToolUseFailure fires instead. This script
detects test commands and records the failure in the SMM.

The input has no tool_response (the tool failed), so we can't parse
detailed pass/fail counts. We record that the test run failed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import bash_post_tool


def run(input_data: dict, smm_dir: Path | None = None) -> None:
    """Record failed test runs in the SMM."""
    if _common.is_xp_agent(input_data):
        return None

    # Skip user interrupts — not a real failure
    if input_data.get("is_interrupt"):
        return None

    # Check if test command before doing any I/O
    command = input_data.get("tool_input", {}).get("command", "")
    framework = bash_post_tool.is_test_run(command)
    if not framework:
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = input_data.get("agent_id", "main")
    error = input_data.get("error", "")

    # Record failure as status + concern
    status = _common.make_event(
        _common.STATUS,
        agent_id,
        f"Test run failed ({framework}): {error}",
        working_on=[],
    )
    _common.append_safe(smm_dir, status)

    concern = _common.make_event(
        _common.CONCERN,
        agent_id,
        f"Test command failed: `{command}` — {error}",
        severity="high",
    )
    _common.append_safe(smm_dir, concern)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
