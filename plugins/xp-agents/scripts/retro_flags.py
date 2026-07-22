#!/usr/bin/env python3
"""Deterministic threshold evaluation for retrospective metrics.

Evaluates honesty signals, work signals, status summary, and session stats
against fixed thresholds. Returns structured flags that the retro agent
uses directly — no LLM judgment on numeric thresholds.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from event_schema import EVENT_TYPE_DECISION, event_action


def _flag(
    metric: str,
    value: int,
    threshold: int,
    xp_value: str,
    message: str,
) -> dict:
    return {
        "metric": metric,
        "value": value,
        "threshold": threshold,
        "category": "fix",
        "xp_value": xp_value,
        "message": message,
    }


_FLAG_SUPPRESSIONS: dict[str, str] = {
    "max_events_to_commit": "retro-try-kickoff-exemption",
}

# --- batch-size flag: threshold and its provenance (story-010) -------------
#
# The batch counter (work_signals.batch_sizes_per_agent) measures ONE agent's
# events from its first code edit through its own next commit, excluding
# test-run telemetry. The threshold below is derived from that counter's own
# output, not inherited.
#
# The previous 75 was carried over from an era when the counter summed every
# agent's events into one global stream. Re-instrumented, the same log peaks
# at 28 — so 75 could never fire again, and a flag that cannot fire is as
# dishonest as one that always does.
#
# Which mechanism keeps this flag quiet, after this change? The THRESHOLD.
# The `retro-try-kickoff-exemption` suppression above is now the secondary
# path: it only engages when that decision is active, whereas the
# re-baselined threshold governs every ordinary session. A future reader
# finding the flag quiet should look here first, not at the suppression.
BATCH_THRESHOLD_BASIS = {
    "source": "xp-agents SMM events.jsonl, the retro's own `unanalyzed` slice",
    "events": 604,
    # Every batch interval that closed in that slice, measured with the
    # post-story-010 counter.
    "closed_intervals": [5, 6, 12, 13, 14, 17, 20, 28],
    "caveat": (
        "n=8 closed intervals from a post-compaction log covering one "
        "sprint of this project — a small, single-project sample. Re-measure "
        "before trusting it as a cross-project default."
    ),
}

# Sits above the sample's p90 (20) and at/below its max (28): quiet on
# ordinary work, still reachable by the worst batch actually observed.
# test_retro_flags_batch.TestBatchThresholdProvenance holds the number inside
# that band — it does not freeze the exact value, but a bump outside what the
# recorded sample supports goes red until the sample is re-measured too.
MAX_EVENTS_TO_COMMIT_THRESHOLD = 25

# Fraction of decision events with metadata.action="explicit_zero" above
# which the retro flags "we keep declining to record decisions" (Honesty lens).
ZERO_DECISION_RATE_THRESHOLD = 0.5


def _count_explicit_zero_decisions(events: list[dict]) -> tuple[int, int]:
    """Return (explicit_zero_count, total_decision_count) over events."""
    zero = 0
    total = 0
    for event in events:
        if event.get("type") != EVENT_TYPE_DECISION:
            continue
        total += 1
        if event_action(event) == "explicit_zero":
            zero += 1
    return zero, total


def evaluate_flags(
    honesty_signals: dict,
    work_signals: dict,
    status_summary: dict,
    session_stats: dict,
    decisions: list[str] | None = None,
    events: list[dict] | None = None,
) -> list[dict]:
    """Evaluate all metrics against thresholds. Returns list of flags."""
    flags: list[dict] = []
    active_decisions = set(decisions) if decisions else set()

    tdd = honesty_signals.get("max_unique_files_without_test", 0)
    refactor_excluded = honesty_signals.get("refactor_mode_excluded_files", 0)
    if tdd >= 5:
        msg = f"TDD gap: {tdd} unique files written without a test run (threshold: 5)"
        if refactor_excluded > 0:
            msg += f", {refactor_excluded} excluded as refactor-mode"
        flags.append(
            _flag(
                "max_unique_files_without_test",
                tdd,
                5,
                "Feedback",
                msg,
            )
        )

    writes = honesty_signals.get("code_file_writes", 0)
    concerns = honesty_signals.get("concerns_raised", 0)
    if writes >= 10 and concerns == 0:
        flags.append(
            _flag(
                "writes_without_concerns",
                writes,
                10,
                "Honesty",
                f"{writes} code file writes with zero concerns raised",
            )
        )

    planning = honesty_signals.get("planning_events", 0)
    assumptions = honesty_signals.get("assumptions_stated", 0)
    if planning > 0 and assumptions == 0:
        flags.append(
            _flag(
                "planning_without_assumptions",
                planning,
                0,
                "Honesty",
                f"{planning} plan(s) created with zero assumptions recorded",
            )
        )

    decisions_total = session_stats.get("decisions_total", 0)
    if planning > 0 and decisions_total == 0:
        flags.append(
            _flag(
                "planning_without_decisions",
                planning,
                0,
                "Communication",
                f"{planning} plan(s) created with zero decisions recorded",
            )
        )

    # concerns_not_addressed: no commits followed any concern (gap in response)
    # unaddressed_concerns: concerns still open at session end (timing)
    addressed = work_signals.get("concerns_addressed_by_commits", 0)
    if concerns > 0 and addressed == 0:
        flags.append(
            _flag(
                "concerns_not_addressed",
                concerns,
                0,
                "Courage",
                f"{concerns} concerns raised but none addressed by commits",
            )
        )

    unaddressed = work_signals.get("unaddressed_concerns", 0)
    if unaddressed > 0:
        flags.append(
            _flag(
                "unaddressed_concerns",
                unaddressed,
                0,
                "Courage",
                f"{unaddressed} concern(s) unaddressed at session end",
            )
        )

    events_to_commit = work_signals.get("max_events_to_commit", 0)
    if events_to_commit >= MAX_EVENTS_TO_COMMIT_THRESHOLD:
        suppressor = _FLAG_SUPPRESSIONS.get("max_events_to_commit")
        if not (suppressor and suppressor in active_decisions):
            # Written from the counter, not from intent: it measures one
            # agent's own events, anchored at that agent's first code edit,
            # closed by that agent's own commit, with test runs excluded.
            # Naming the agent is what makes "commit sooner" actionable —
            # the reader knows whose batch this was.
            batch_agent = work_signals.get("max_events_to_commit_agent") or "one agent"
            flags.append(
                _flag(
                    "max_events_to_commit",
                    events_to_commit,
                    MAX_EVENTS_TO_COMMIT_THRESHOLD,
                    "Simplicity",
                    f"Large batch: {batch_agent} accumulated "
                    f"{events_to_commit} events between its first code edit "
                    f"and its own commit, excluding test runs "
                    f"(threshold: {MAX_EVENTS_TO_COMMIT_THRESHOLD})",
                )
            )

    test_failures = work_signals.get("max_consecutive_test_failures", 0)
    if test_failures >= 3:
        flags.append(
            _flag(
                "max_consecutive_test_failures",
                test_failures,
                3,
                "Simplicity",
                f"{test_failures} consecutive test failures — investigate root cause",
            )
        )

    raised = session_stats.get("concerns_raised", 0)
    resolved = session_stats.get("concerns_resolved", 0)
    if raised - resolved > 3:
        flags.append(
            _flag(
                "unresolved_concerns",
                raised - resolved,
                3,
                "Feedback",
                f"{raised - resolved} concerns unresolved "
                f"(raised: {raised}, resolved: {resolved})",
            )
        )

    questions = session_stats.get("questions_open", 0)
    if questions > 0:
        flags.append(
            _flag(
                "questions_open",
                questions,
                0,
                "Communication",
                f"{questions} question(s) unanswered at session end",
            )
        )

    review_required = honesty_signals.get("review_required_commits", 0)
    reviews = status_summary.get("quality_reviews", 0)
    if review_required > 0 and reviews < review_required:
        flags.append(
            _flag(
                "quality_reviews_missing",
                reviews,
                review_required,
                "Feedback",
                f"{reviews} quality reviews for"
                f" {review_required} review-required commits",
            )
        )

    if events is not None:
        zero, total = _count_explicit_zero_decisions(events)
        if total > 0 and zero / total > ZERO_DECISION_RATE_THRESHOLD:
            pct = round(zero * 100 / total)
            threshold_pct = int(ZERO_DECISION_RATE_THRESHOLD * 100)
            flags.append(
                _flag(
                    "high_zero_decision_rate",
                    pct,
                    threshold_pct,
                    "Honesty",
                    f"{pct}% of decisions are explicit_zero "
                    f"({zero}/{total}) — recording 'no decision' too often "
                    f"(threshold: {threshold_pct}%)",
                )
            )

    return flags
