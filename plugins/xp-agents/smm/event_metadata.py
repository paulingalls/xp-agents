#!/usr/bin/env python3
"""Metadata vocabulary: STATUS_ACTION_*, METADATA_KEY_*, DISPOSITION_*,
RETRO_ACTION_*, CONCERN_KIND_* string constants.

Extracted from event_schema.py (split-shim convention 91fcf9b8744d) when
event_schema.py crossed 500 lines. event_schema.py re-exports every name
here so callers continue to `from event_schema import STATUS_ACTION_*`
without churn.

Pure string-leaf constants — zero dependencies on other event_schema
symbols, so this module has no circular-import risk with event_schema.
"""

# Status event metadata.action discriminators — used by cascading gates
# to identify specific lifecycle events without scanning content strings.
STATUS_ACTION_ITERATION_COMPLETE = "iteration_complete"
STATUS_ACTION_SPRINT_RETRO_DONE = "sprint_retro_done"

# Review-cycle lifecycle actions — vocabulary for the deterministic-event
# doctrine. The sole producer is review_cycle_done.py, which
# sets metadata.action to one of these values so consumers (retro_metrics,
# bash_post_tool) can detect skill completions without regex-matching
# LLM-authored content.
STATUS_ACTION_SIMPLIFY_COMPLETE = "simplify_complete"
STATUS_ACTION_QR_COMPLETE = "qr_complete"
STATUS_ACTION_SECURITY_COMPLETE = "security_complete"
STATUS_ACTION_PLAN_REVIEWED = "plan_reviewed"
STATUS_ACTION_ASSIGN_COMPLETE = "assign_complete"
STATUS_ACTION_HOUSEKEEPING_COMPLETE = "housekeeping_complete"

# Tool-action lifecycle vocabulary — extends the review-cycle doctrine
# above with structured tool events. Each constant is emitted by exactly
# one hook; consumers read
# metadata.action so structured fields (files, exit_code, framework, etc.)
# are not parsed back out of LLM-authored content. Producer map:
#   STATUS_ACTION_FILE_WRITE        — post_tool_use.py (Write/Edit/MultiEdit)
#   STATUS_ACTION_TEST_RUN_COMPLETE — bash_post_tool.py (test command success)
#   STATUS_ACTION_LINT_RESOLVED     — lint_resolution.py (lint resolved on commit)
#   STATUS_ACTION_BASH_FAILED       — bash_failure.py (Bash exit non-zero)
#   STATUS_ACTION_COMMIT_SUCCESS    — bash_post_tool.py (git commit, type=commit)
STATUS_ACTION_FILE_WRITE = "file_write"
STATUS_ACTION_TEST_RUN_COMPLETE = "test_run_complete"
STATUS_ACTION_LINT_RESOLVED = "lint_resolved"
STATUS_ACTION_BASH_FAILED = "bash_failed"
STATUS_ACTION_COMMIT_SUCCESS = "commit_success"

# Subagent + plan lifecycle vocabulary — extends the tool-action wave
# with subagent stop signals. Closes the cleanup window opened by the
# prior tool-action vocabulary. Producer map:
#   STATUS_ACTION_SUBAGENT_COMPLETE     — subagent_stop.py (every subagent)
#   STATUS_ACTION_PLAN_COMPLETED        — subagent_stop.py (Plan subagent stop)
#   STATUS_ACTION_PLAN_AWAITING_REVIEW  — subagent_stop.py (Plan subagent gate)
#   STATUS_ACTION_PLAN_EXITED           — post_tool_exit_plan.py (ExitPlanMode)
STATUS_ACTION_SUBAGENT_COMPLETE = "subagent_complete"
STATUS_ACTION_PLAN_COMPLETED = "plan_completed"
STATUS_ACTION_PLAN_AWAITING_REVIEW = "plan_awaiting_review"
STATUS_ACTION_PLAN_EXITED = "plan_exited"

# Step 5c (close skills) — concern classification per finding.
# Producer: story-close + free-close at Step 5c (LLM via append.sh).
# Consumer: count-classifications subcommand for the Step 6 auto-merge
# gate; retro tooling for prediction-loop validation.
# Companion metadata fields the producer also sets:
#   metadata.route       — "fix" | "ask" — which dispatch route the LLM took.
#   metadata.category    — classification vocabulary (lint, test_failure, ...).
#   metadata.concern_id  — the 12-hex ID of the concern being classified.
STATUS_ACTION_CONCERN_CLASSIFY = "concern_classify"

# Question-close (won't-fix) discriminator. Producer: smm_cli question close
# --won-fix. Consumer: question-aging tooling, which already treats this
# metadata combination (action=question_close + disposition=wont_fix +
# resolves=[Q]) as a terminal disposition via metadata.resolves alone.
STATUS_ACTION_QUESTION_CLOSE = "question_close"

# End-of-session bulk-drop discriminator. Producer: xp-end-session skill
# Step 3 (LLM-judged auto-resolve of LIKELY_ADDRESSED concerns/debts).
# Companion metadata: METADATA_KEY_RESOLVES (canonical STRONG link to the
# concern/debt being closed) + METADATA_KEY_RESOLVED_BY_COMMITS (audit
# trail of which commit IDs informed the auto-judge). Consumer: retro
# tooling distinguishes end-session bulk drops from organic resolutions.
STATUS_ACTION_END_SESSION_DROP = "end_session_drop"


def event_action(event: dict) -> str | None:
    """Return event.metadata.action, or None when absent.

    Centralized accessor so consumers don't repeat the
    `e.get("metadata", {}).get("action")` pattern (which also allocates a
    fresh empty dict on every miss). Returns None for legacy events without
    metadata or without the action discriminator.
    """
    metadata = event.get("metadata")
    if not metadata:
        return None
    return metadata.get("action")


# Cross-module metadata keys. Centralized here so producer and consumer
# cannot drift on the spelling.
#   METADATA_KEY_RESOLVES       — STRONG resolution link: event IDs this
#                                 event closes. Shape: list[str] of
#                                 12-hex-char IDs (validate_event rejects
#                                 scalars; resolution.py iterates the list).
#                                 Written by bash_post_tool, concerns,
#                                 and work_selection_decide; read by
#                                 pre_tool_bash, retrospective,
#                                 materialize, resolution.
#   METADATA_KEY_COMMIT_HASH    — git HEAD hash recorded on commit events
#                                 (bash_post_tool.py).
#   METADATA_KEY_RESOLVED_BY_COMMITS — commit event IDs that informed an
#                                 end-session auto-resolve decision (audit
#                                 trail; orthogonal to RESOLVES which is the
#                                 STRONG link). Producer: xp-end-session
#                                 status events with action=end_session_drop.
METADATA_KEY_RESOLVES = "resolves"
METADATA_KEY_SUPERSEDES = "supersedes"
METADATA_KEY_COMMIT_HASH = "commit_hash"
METADATA_KEY_RESOLVED_BY_COMMITS = "resolved_by_commits"

# Concern metadata.kind discriminator vocabulary. Centralized so producer
# (close_cycle_stop_gate hook) and consumer (retros, integration tests)
# can't drift on the spelling. Pattern matches STATUS_ACTION_* — a small
# string vocab named at module level, not inlined.
CONCERN_KIND_CLOSE_CYCLE_BYPASS = "close_cycle_bypass"

# tdd_red: producer (bash_post_tool) tags test_run_complete events when
# the prior commit was test-only (RED step in TDD); consumer
# (work_signals) skips them from consecutive_failures so legitimate
# red TDD doesn't surface as a regression streak.
METADATA_KEY_TDD_RED = "tdd_red"
METADATA_KEY_DISPOSITION = "disposition"
METADATA_KEY_CLOSE_MODE = "close_mode"
METADATA_KEY_CLOSE_CYCLE_ID = "close_cycle_id"
# Set on a status event with disposition=deferred when the user forces a
# defer past the FORCE-CLOSE gate via --force-defer-with-date; YYYY-MM-DD.
METADATA_KEY_DEFER_UNTIL = "defer_until"

# Stale-concern sweep (session_end._sweep_stale_concerns) flag-concern keys.
# Carried on a NEW concern event with references=[orig_id]; the WEAK cascade
# (resolution.compute_resolutions) closes the flag when orig_id resolves.
# Producer: session_end. Consumer: session_end (idempotency check) + retro
# Fix-lens (xp-retrospective surfaces flagged concerns for human triage).
METADATA_KEY_FLAGGED_STALE = "flagged_stale"
METADATA_KEY_STALE_SESSION_COUNT = "stale_session_count"

# Retro Try disposition values written to metadata.disposition by
# work_selection_decide (adopt/defer/drop) and read by retro_history,
# subagent_start. Centralized to prevent producer/consumer drift.
DISPOSITION_ADOPTED = "adopted"
DISPOSITION_DEFERRED = "deferred"
DISPOSITION_DROPPED = "dropped"
# question close --won-fix disposition. Paired with
# STATUS_ACTION_QUESTION_CLOSE on a status event resolving a question id
# via metadata.resolves.
DISPOSITION_WONT_FIX = "wont_fix"

# Retrospective event metadata.action discriminators — distinguish session
# retros from sprint retros so the session-start watermark scanner only
# advances on session retros. Without this, a sprint retro at end of session
# poisons the next session's retro detection.
RETRO_ACTION_SESSION_DONE = "session_retro_done"
RETRO_ACTION_SPRINT_DONE = "sprint_retro_done"
