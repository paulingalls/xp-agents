#!/usr/bin/env python3
"""Stop command hook: TDD gate.

Blocks stop when the most recent test run in the event log failed.
Replaces the tdd_check.md prompt hook with deterministic event parsing.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import concerns

# Patterns that indicate test results in status/concern events
_TEST_PASS_RE = re.compile(
    r"Tests?:.*\d+\s+passed.*0\s+failed"  # "Tests: 5 passed, 0 failed (pytest)"
    r"|Tests?\s+passed\b",  # "Tests passed (pytest)" — fallback
    re.IGNORECASE,
)
_TEST_FAIL_RE = concerns.TEST_CONCERN_RE


def _find_last_test_signal(events: list[dict]) -> str | None:
    """Scan events from end. Return 'pass', 'fail', or None.

    Skips resolved concerns — a resolved test failure should not block stop.
    """
    from _append_impl import compute_resolutions

    resolved_ids = compute_resolutions(events)["resolved_concern_ids"]

    for e in reversed(events):
        content = e.get("content", "")
        etype = e.get("type", "")
        if (
            etype == _common.CONCERN
            and _TEST_FAIL_RE.search(content)
            and e.get("id", "") not in resolved_ids
        ):
            return "fail"
        if etype == _common.STATUS and _TEST_PASS_RE.search(content):
            return "pass"
    return None


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Return block reason if tests failing, None otherwise."""
    if _common.is_xp_agent(input_data):
        return None
    if input_data.get("stop_hook_active"):
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_raw(smm_dir)
    if not events:
        return None

    signal = _find_last_test_signal(events)
    if signal == "fail":
        return "Tests are failing. Fix failing tests before stopping."

    return None


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result:
        _common.block_output(result, "Test failures detected — fix before stopping.")
    sys.exit(0)
