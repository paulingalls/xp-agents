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
import code_files
from event_schema import (
    METADATA_KEY_TDD_RED,
    STATUS_ACTION_COMMIT_SUCCESS,
    STATUS_ACTION_TEST_RUN_COMPLETE,
    event_action,
)
from test_parsing import PARSER_STATUS_FAILED

# Parses failed-count from content when metadata.test_passed is absent and
# parser_status didn't flag the run as parser_failed. NOT a status-event
# content fallback for test-run detection (action dispatch handles that).
_TEST_FAIL_RE = re.compile(r"(\d+)\s+failed", re.IGNORECASE)


def _has_code_changes(event: dict) -> bool:
    """Check if event represents a code file write (not config/docs)."""
    working_on = event.get("working_on", [])
    if not isinstance(working_on, list):
        return False
    return any(code_files.is_code_file(f) for f in working_on)


# Per-tool-call telemetry excluded from the batch count. A TDD cycle that
# runs the suite five times has not accumulated five more units of unshipped
# work, and counting it would score the Feedback value as a defect. Edits are
# deliberately NOT excluded — they ARE the work being batched, and dropping
# them would leave the metric blind to a run that edits twenty files before
# committing.
_BATCH_EXCLUDED_ACTIONS = frozenset({STATUS_ACTION_TEST_RUN_COMPLETE})


def batch_sizes_per_agent(events: list[dict]) -> dict[str, int]:
    """Largest batch each agent accumulated before one of its own commits.

    Deliberately NOT "everything since its last commit" — that was the old,
    defective definition this replaces.

    THE canonical definition of ``max_events_to_commit``. A batch is ONE
    agent's events from its first code edit through its next commit,
    excluding test-run telemetry. The partition by ``agent_id`` is what
    makes the derived flag actionable: a teammate's events never inflate
    another agent's batch, so the agent the flag names is the agent who can
    shrink it by committing sooner.

    Events before an agent's first code edit do not count — planning is not
    batching. An agent with no closed interval is ABSENT from the result
    rather than reported as zero: an agent that never commits (every
    reviewer, every skill) has no batch, which is a different claim from
    having an empty one.

    Both producers of ``max_events_to_commit`` — the retro flag here and
    the per-agent prose figures in story_metrics — call this, so the key
    cannot come to mean two things again (story-010).
    """
    open_batches: dict[str, int] = {}
    maxima: dict[str, int] = {}

    for e in events:
        agent = e.get("agent_id", "main")
        action = event_action(e)
        is_commit = (
            e.get("type") == _common.COMMIT or action == STATUS_ACTION_COMMIT_SUCCESS
        )

        if is_commit:
            batch = open_batches.pop(agent, None)
            if batch is not None:
                maxima[agent] = max(maxima.get(agent, 0), batch)
        elif action in _BATCH_EXCLUDED_ACTIONS:
            # Excluded events cannot open an interval they don't count in.
            continue
        elif agent in open_batches:
            open_batches[agent] += 1
        elif _has_code_changes(e):
            open_batches[agent] = 1

    return maxima


def _max_batch(events: list[dict]) -> tuple[int, str | None]:
    """The single worst batch and the agent that accumulated it.

    Returns ``(0, None)`` when no interval ever closed — there is no batch
    to name.
    """
    maxima = batch_sizes_per_agent(events)
    if not maxima:
        return 0, None
    agent = max(maxima, key=lambda a: maxima[a])
    return maxima[agent], agent


def build_work_signals(events: list[dict]) -> dict:
    """Analyze event sequence for work-level signals.

    Complements honesty_signals (process compliance) with signals about
    what was accomplished, what was difficult, and whether intent was
    followed through.
    """
    pending_concerns = 0
    concerns_addressed = 0

    consecutive_failures = 0
    max_consecutive_failures = 0

    max_events_to_commit, batch_agent = _max_batch(events)

    for e in events:
        etype = e.get("type", "")
        content = e.get("content", "")
        action = event_action(e)

        # Real commits are type=commit; the action branch is forward-compat
        # for any future status-typed commit emission.
        is_commit = etype == _common.COMMIT or action == STATUS_ACTION_COMMIT_SUCCESS

        if is_commit:
            # Concerns before this commit are now addressed
            concerns_addressed += pending_concerns
            pending_concerns = 0
        else:
            is_test_run = action == STATUS_ACTION_TEST_RUN_COMPLETE

            if etype == _common.CONCERN:
                pending_concerns += 1
            elif is_test_run:
                # parser_failed carries no signal — skip so a "don't know"
                # outcome doesn't green-wash an in-flight red streak.
                # tdd_red is producer-tagged when the prior commit was
                # test-only (RED step in TDD); skip too — the failure is
                # expected, not a regression. Same treatment as
                # parser_failed: don't reset the streak, don't increment.
                metadata = e.get("metadata") or {}
                if metadata.get("parser_status") == PARSER_STATUS_FAILED:
                    continue
                if metadata.get(METADATA_KEY_TDD_RED):
                    continue
                # Prefer structured metadata.test_passed when present;
                # otherwise fall back to parsing failed-count from content.
                if "test_passed" in metadata:
                    failed_count = 0 if metadata["test_passed"] else 1
                else:
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

    return {
        "concerns_addressed_by_commits": concerns_addressed,
        "unaddressed_concerns": pending_concerns,
        "max_consecutive_test_failures": max_consecutive_failures,
        "max_events_to_commit": max_events_to_commit,
        "max_events_to_commit_agent": batch_agent,
    }
