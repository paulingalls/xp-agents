#!/usr/bin/env python3
"""Honesty signal computation for retrospective analysis.

Analyzes event sequences for TDD discipline, security triage coverage,
planning activity, and other process health indicators. Extracted from
retrospective.py to keep modules under 500 lines.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import security

_FILE_WRITE_RE = re.compile(r"Wrote to\b", re.IGNORECASE)
_TEST_RUN_RE = _common.TEST_RUN_RE
_SECURITY_CHECK_RE = _common.SECURITY_CHECK_RE
_COMMIT_RE = _common.LEGACY_COMMIT_RE
_PLAN_RE = re.compile(r"plan_awaiting_review:", re.IGNORECASE)


def build_honesty_signals(events: list[dict]) -> dict:
    """Analyze event sequence for honesty red flags.

    Looks at ordering and gaps, not just counts — gives the retro
    concrete data to reason about instead of inferring from totals.
    """
    signals: dict = {}

    unique_files_since_test: set[str] = set()
    max_unique_files_without_test = 0
    commits_without_triage = 0
    total_commits = 0
    code_commits = 0
    last_security_check_seen = False
    concern_count = 0
    assumption_count = 0
    file_write_count = 0
    planning_events = 0

    from pre_tool_write import is_test_file

    for e in events:
        etype = e.get("type", "")
        content = e.get("content", "")

        is_commit = etype == _common.COMMIT or (
            etype == _common.STATUS and _COMMIT_RE.search(content)
        )
        if is_commit:
            total_commits += 1
            is_code = e.get("metadata", {}).get("code_commit", True)
            if is_code:
                code_commits += 1
            if not last_security_check_seen and is_code:
                commits_without_triage += 1
            last_security_check_seen = False
        elif etype == _common.STATUS:
            if _FILE_WRITE_RE.search(content):
                path = content.replace("Wrote to ", "").strip()
                if security.is_code_file(path):
                    file_write_count += 1
                    if not is_test_file(path):
                        unique_files_since_test.add(path)
            elif _TEST_RUN_RE.search(content):
                max_unique_files_without_test = max(
                    max_unique_files_without_test,
                    len(unique_files_since_test),
                )
                unique_files_since_test = set()
            elif _SECURITY_CHECK_RE.search(content):
                last_security_check_seen = True
            elif _PLAN_RE.search(content):
                planning_events += 1
        elif etype == _common.CONCERN:
            concern_count += 1
        elif etype == _common.ASSUMPTION:
            assumption_count += 1

    max_unique_files_without_test = max(
        max_unique_files_without_test, len(unique_files_since_test)
    )

    signals["max_unique_files_without_test"] = max_unique_files_without_test
    signals["commits_without_triage"] = commits_without_triage
    signals["total_commits"] = total_commits
    signals["code_file_writes"] = file_write_count
    signals["concerns_raised"] = concern_count
    signals["assumptions_stated"] = assumption_count
    signals["code_commits"] = code_commits
    signals["planning_events"] = planning_events

    return signals
