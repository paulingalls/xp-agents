#!/usr/bin/env python3
"""Deterministic threshold evaluation for retrospective metrics.

Evaluates honesty signals, work signals, status summary, and session stats
against fixed thresholds. Returns structured flags that the retro agent
uses directly — no LLM judgment on numeric thresholds.
"""


def _flag(
    metric: str,
    value: object,
    threshold: object,
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


def evaluate_flags(
    honesty_signals: dict,
    work_signals: dict,
    status_summary: dict,
    session_stats: dict,
    decisions: list[str] | None = None,
) -> list[dict]:
    """Evaluate all metrics against thresholds. Returns list of flags."""
    flags: list[dict] = []
    active_decisions = set(decisions) if decisions else set()

    tdd = honesty_signals.get("max_unique_files_without_test", 0)
    if tdd >= 5:
        flags.append(
            _flag(
                "max_unique_files_without_test",
                tdd,
                5,
                "Feedback",
                f"TDD gap: {tdd} unique files written "
                f"without a test run (threshold: 5)",
            )
        )

    without_security_check = honesty_signals.get("commits_without_security_check", 0)
    if without_security_check > 0:
        flags.append(
            _flag(
                "commits_without_security_check",
                without_security_check,
                0,
                "Honesty",
                f"{without_security_check} code commit(s) without a security check "
                f"(triage or review)",
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

    decisions = session_stats.get("decisions_total", 0)
    if planning > 0 and decisions == 0:
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
    if events_to_commit >= 50:
        suppressor = _FLAG_SUPPRESSIONS.get("max_events_to_commit")
        if not (suppressor and suppressor in active_decisions):
            flags.append(
                _flag(
                    "max_events_to_commit",
                    events_to_commit,
                    50,
                    "Simplicity",
                    f"Large batch: {events_to_commit} events between "
                    f"first edit and commit (threshold: 50)",
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

    return flags
