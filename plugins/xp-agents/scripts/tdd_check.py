#!/usr/bin/env python3
"""Shared TDD check: find the last test signal in the event log.

Extracted from tdd_stop_gate.py for reuse by TeammateIdle and
TaskCompleted hooks (M13). All three hooks need the same logic:
scan events in reverse, skip resolved concerns, return pass/fail/None.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import concerns
import resolution

# Patterns that indicate test results in status/concern events
TEST_PASS_RE = re.compile(
    r"Tests?:.*\d+\s+passed.*0\s+failed"
    r"|Tests?\s+passed\b",
    re.IGNORECASE,
)
TEST_FAIL_RE = concerns.TEST_CONCERN_RE


def find_last_test_signal(events: list[dict]) -> str | None:
    """Scan events from end. Return 'pass', 'fail', or None.

    Skips resolved concerns — a resolved test failure should not block.
    """
    resolved_ids = resolution.compute_resolutions(events)["resolved_concern_ids"]

    for e in reversed(events):
        content = e.get("content", "")
        etype = e.get("type", "")
        if (
            etype == _common.CONCERN
            and TEST_FAIL_RE.search(content)
            and e.get("id", "") not in resolved_ids
        ):
            return "fail"
        if etype == _common.STATUS and TEST_PASS_RE.search(content):
            return "pass"
    return None
