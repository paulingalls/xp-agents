#!/usr/bin/env python3
"""Honesty signal computation for retrospective analysis.

Analyzes event sequences for TDD discipline, planning activity, and other
process health indicators. Extracted from retrospective.py to keep modules
under 500 lines.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import code_files
import commits
from commits import REVIEW_CYCLE_THRESHOLD
from event_schema import (
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
    event_action,
)

_PLAN_RE = re.compile(r"plan_awaiting_review:", re.IGNORECASE)
_REFACTOR_MODE_RE = re.compile(r"refactor.mode", re.IGNORECASE)


def build_honesty_signals(events: list[dict]) -> dict:
    """Analyze event sequence for honesty red flags.

    Looks at ordering and gaps, not just counts — gives the retro
    concrete data to reason about instead of inferring from totals.
    """
    signals: dict = {}

    unique_files_since_test: set[str] = set()
    max_unique_files_without_test = 0
    total_commits = 0
    code_commits = 0
    review_required_commits = 0
    concern_count = 0
    assumption_count = 0
    file_write_count = 0
    planning_events = 0
    in_refactor_mode = False
    refactor_mode_excluded: set[str] = set()

    from pre_tool_write import is_test_file

    for e in events:
        etype = e.get("type", "")
        content = e.get("content", "")

        if etype == _common.COMMIT:
            total_commits += 1
            in_refactor_mode = False
            meta = e.get("metadata", {})
            is_code = meta.get("code_commit", True)
            if is_code:
                code_commits += 1
                cfc = meta.get("code_file_count")
                # Merge HEADs aggregate already-reviewed work; escape-hatch
                # commits ([release]/[chore]/[sprint-direct]) bypass the
                # review-cycle gate by design; story-cadence commits defer their
                # review to /xp-story-close (which reviews the cumulative diff
                # and ticks quality_reviews once). None requires its own
                # per-commit review, so none belongs in the review-required
                # denominator — counting them is a quality_reviews_missing
                # false positive (the Feedback flag fires on merge/release noise
                # or, in story mode, on the by-design reviews-fewer-than-commits).
                review_exempt = (
                    meta.get("is_merge")
                    or commits.is_escape_hatch_message(content)
                    or meta.get("review_cadence") == "story"
                )
                if not review_exempt and (cfc is None or cfc >= REVIEW_CYCLE_THRESHOLD):
                    review_required_commits += 1
        elif etype == _common.STATUS:
            action = event_action(e)
            if action == STATUS_ACTION_FILE_WRITE:
                # Path comes from metadata.files[0] — content is opaque.
                files = (e.get("metadata") or {}).get("files") or []
                path = files[0] if files else None
                if path and code_files.is_code_file(path):
                    file_write_count += 1
                    if not is_test_file(path):
                        target = (
                            refactor_mode_excluded
                            if in_refactor_mode
                            else unique_files_since_test
                        )
                        target.add(path)
            elif action == STATUS_ACTION_TEST_RUN_COMPLETE:
                max_unique_files_without_test = max(
                    max_unique_files_without_test,
                    len(unique_files_since_test),
                )
                unique_files_since_test = set()
            elif _PLAN_RE.search(content):
                planning_events += 1
        elif etype == _common.CONCERN:
            concern_count += 1
        elif etype == _common.ASSUMPTION:
            assumption_count += 1
            if _REFACTOR_MODE_RE.search(content):
                in_refactor_mode = True

    max_unique_files_without_test = max(
        max_unique_files_without_test, len(unique_files_since_test)
    )

    signals["max_unique_files_without_test"] = max_unique_files_without_test
    signals["refactor_mode_excluded_files"] = len(refactor_mode_excluded)
    signals["total_commits"] = total_commits
    signals["code_file_writes"] = file_write_count
    signals["concerns_raised"] = concern_count
    signals["assumptions_stated"] = assumption_count
    signals["code_commits"] = code_commits
    signals["review_required_commits"] = review_required_commits
    signals["planning_events"] = planning_events

    return signals
