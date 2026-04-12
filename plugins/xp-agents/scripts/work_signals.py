#!/usr/bin/env python3
"""Work signals for retrospective analysis.

Pre-computes correlations between concerns, decisions, commits, and test
results that the retro agent uses alongside signal_events to analyze
what was accomplished and what was difficult.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common

_TEST_RUN_RE = _common.TEST_RUN_RE
_TEST_FAIL_RE = re.compile(r"(\d+)\s+failed", re.IGNORECASE)
_COMMIT_RE = _common.LEGACY_COMMIT_RE


def _has_code_changes(event: dict) -> bool:
    """Check if event represents a code change (non-empty working_on)."""
    working_on = event.get("working_on", [])
    return isinstance(working_on, list) and len(working_on) > 0


def build_work_signals(events: list[dict]) -> dict:
    """Analyze event sequence for work-level signals.

    Complements honesty_signals (process compliance) with signals about
    what was accomplished, what was difficult, and whether intent was
    followed through.
    """
    pending_concerns = 0
    concerns_addressed = 0
    pending_decisions = 0
    decisions_without_commits = 0

    consecutive_failures = 0
    max_consecutive_failures = 0

    events_since_first_edit = 0
    max_events_to_commit = 0
    editing = False

    for e in events:
        etype = e.get("type", "")
        content = e.get("content", "")

        is_commit = etype == _common.COMMIT or (
            etype == _common.STATUS and _COMMIT_RE.search(content)
        )

        if is_commit:
            # Concerns before this commit are now addressed
            concerns_addressed += pending_concerns
            pending_concerns = 0
            # Decisions before this commit are implemented
            pending_decisions = 0
            # Track events from first edit to commit
            if editing:
                max_events_to_commit = max(
                    max_events_to_commit, events_since_first_edit
                )
            events_since_first_edit = 0
            editing = False
        else:
            # Start counting from first code change
            if not editing and _has_code_changes(e):
                editing = True
                events_since_first_edit = 1
            elif editing:
                events_since_first_edit += 1

            if etype == _common.CONCERN:
                pending_concerns += 1
            elif etype == _common.DECISION:
                pending_decisions += 1
            elif etype == _common.STATUS and _TEST_RUN_RE.search(content):
                fail_match = _TEST_FAIL_RE.search(content)
                failed_count = int(fail_match.group(1)) if fail_match else 0
                if failed_count > 0:
                    consecutive_failures += 1
                else:
                    max_consecutive_failures = max(
                        max_consecutive_failures, consecutive_failures
                    )
                    consecutive_failures = 0

    # Final streaks
    max_consecutive_failures = max(max_consecutive_failures, consecutive_failures)
    decisions_without_commits = pending_decisions

    return {
        "concerns_addressed_by_commits": concerns_addressed,
        "unaddressed_concerns": pending_concerns,
        "decisions_without_commits": decisions_without_commits,
        "max_consecutive_test_failures": max_consecutive_failures,
        "max_events_to_commit": max_events_to_commit,
    }
