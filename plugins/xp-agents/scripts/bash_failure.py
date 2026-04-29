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
import concerns
import identity
from event_schema import CONTENT_BUDGETS, STATUS_ACTION_BASH_FAILED


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

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    agent_id = identity.resolve_agent_id(input_data)
    try:
        _common._validate_agent_id(agent_id)
    except ValueError:
        return None
    error = input_data.get("error", "")

    # Record failure as status + concern. M2 dual-emit: metadata.action +
    # exit_code (when provided by the hook input) are the canonical signal;
    # content stays as the legacy human-readable digest.
    prefix = f"Test run failed ({framework}): "
    budget = CONTENT_BUDGETS[_common.STATUS]
    assert budget is not None
    max_error = budget - len(prefix)
    metadata: dict = {"action": STATUS_ACTION_BASH_FAILED}
    exit_code = input_data.get("exit_code")
    if exit_code is not None:
        metadata["exit_code"] = exit_code
    status = _common.make_event(
        _common.STATUS,
        agent_id,
        f"{prefix}{error[:max_error]}",
        working_on=[],
        metadata=metadata,
    )
    _common.append_safe(smm_dir, status)

    # Concise concern — the agent already saw the full error in the tool response
    first_line = error.split("\n", 1)[0].strip() if error else "exit non-zero"
    concern = _common.make_event(
        _common.CONCERN,
        agent_id,
        f"{concerns.TEST_COMMAND_FAILED_PREFIX} ({framework}): {first_line}",
        severity="high",
    )
    _common.append_safe(smm_dir, concern)

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    run(input_data)
    sys.exit(0)
