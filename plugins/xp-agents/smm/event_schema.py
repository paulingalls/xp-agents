#!/usr/bin/env python3
"""Event schema: type constants, validation rules, and field constraints.

Single source of truth for what constitutes a valid event. No I/O, no
file operations — pure validation logic and shared constants.

Extracted from _append_impl.py for module size management.
"""

import bisect

from smm_schema import EVENT_ID_RE

# ---------------------------------------------------------------------------
# Session aging utility
# ---------------------------------------------------------------------------


def sessions_since_event(se_timestamps: list[str], event_ts: str) -> int:
    """Count session_end events that occurred after *event_ts*.

    *se_timestamps* must be sorted ascending (ISO-8601 strings).
    Returns 0 when there are no session_end timestamps or the event
    is newer than all of them.
    """
    return len(se_timestamps) - bisect.bisect_right(se_timestamps, event_ts)


# ---------------------------------------------------------------------------
# Event type and field constants
# ---------------------------------------------------------------------------

EVENT_TYPE_ANSWER = "answer"
EVENT_TYPE_ASSUMPTION = "assumption"
EVENT_TYPE_COMMIT = "commit"
EVENT_TYPE_CONCERN = "concern"
EVENT_TYPE_CONVENTION = "convention"
EVENT_TYPE_CUSTOMER_INPUT = "customer_input"
EVENT_TYPE_CUSTOMER_INTENT = "customer_intent"
EVENT_TYPE_DEBT = "debt"
EVENT_TYPE_DECISION = "decision"
EVENT_TYPE_DISCOVERY = "discovery"
EVENT_TYPE_GOAL = "goal"
EVENT_TYPE_QUESTION = "question"
EVENT_TYPE_RETROSPECTIVE = "retrospective"
EVENT_TYPE_SESSION_END = "session_end"
EVENT_TYPE_SESSION_SUMMARY = "session_summary"
EVENT_TYPE_SPRINT = "sprint"
EVENT_TYPE_STATUS = "status"

VALID_TYPES = sorted(
    [
        EVENT_TYPE_ANSWER,
        EVENT_TYPE_ASSUMPTION,
        EVENT_TYPE_COMMIT,
        EVENT_TYPE_CONCERN,
        EVENT_TYPE_CONVENTION,
        EVENT_TYPE_CUSTOMER_INPUT,
        EVENT_TYPE_CUSTOMER_INTENT,
        EVENT_TYPE_DEBT,
        EVENT_TYPE_DECISION,
        EVENT_TYPE_DISCOVERY,
        EVENT_TYPE_GOAL,
        EVENT_TYPE_QUESTION,
        EVENT_TYPE_RETROSPECTIVE,
        EVENT_TYPE_SESSION_END,
        EVENT_TYPE_SESSION_SUMMARY,
        EVENT_TYPE_SPRINT,
        EVENT_TYPE_STATUS,
    ]
)

PRIORITY_BLOCKING = "\U0001f534"  # 🔴
PRIORITY_ASSUMED = "\U0001f7e1"  # 🟡
PRIORITY_INFO = "\U0001f7e2"  # 🟢
VALID_PRIORITIES = frozenset({PRIORITY_BLOCKING, PRIORITY_ASSUMED, PRIORITY_INFO})
VALID_SEVERITIES = frozenset({"high", "medium", "low"})
SPRINT_ACTION_START = "start"
SPRINT_ACTION_END = "end"
VALID_SPRINT_ACTIONS = frozenset({SPRINT_ACTION_START, SPRINT_ACTION_END})
VALID_INTENT_STATUSES = frozenset({"open", "delivered", "superseded"})

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
# Producer/consumer wiring lands in stories 002-004.
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
# Producer/consumer wiring lands in stories 003-006.
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
#   METADATA_KEY_PROBE_CANDIDATES — ids surfaced by the resolves-trailer
#                                 probe; paired with the status-content
#                                 discriminator below.
#   METADATA_KEY_RESOLVED_BY_COMMITS — commit event IDs that informed an
#                                 end-session auto-resolve decision (audit
#                                 trail; orthogonal to RESOLVES which is the
#                                 STRONG link). Producer: xp-end-session
#                                 status events with action=end_session_drop.
METADATA_KEY_RESOLVES = "resolves"
METADATA_KEY_SUPERSEDES = "supersedes"
METADATA_KEY_COMMIT_HASH = "commit_hash"
METADATA_KEY_PROBE_CANDIDATES = "probe_candidates"
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

# Per-candidate selector signals attached by resolves_probe._score_candidate
# and persisted on probe status events so retro_metrics can attribute
# divert events to specific signals (which selector misfired). Shape:
#   {candidate_id: [reason1, reason2, ...]}
# Reason vocabulary is the SELECTION_REASON_* constants below. An empty
# list is ambiguous: it can mean either "old archived probe event predates
# this metadata key" OR "all four signals scored zero on this candidate";
# divert-analysis consumers must treat both cases as 'no signal data'.
METADATA_KEY_PROBE_SELECTION_REASONS = "probe_selection_reasons"

# Snapshot-freshness telemetry attached to probe status events. The
# probe captures both:
#   probe_snapshot_max_ts — newest ts in the caller's events snapshot at
#                           probe entry, BEFORE any staleness reread.
#   probe_tail_ts         — newest ts after the staleness check (post-
#                           reread when triggered, same as snapshot_max
#                           when not).
# When they differ, the probe re-read disk between caller-snapshot and
# probe-time. Lets retro_metrics distinguish "agent picked an event the
# probe never saw" from "agent picked an event that arrived after the
# caller snapshot but before commit" — the second class is closable by
# the staleness reload, the first needs a different fix. Producer:
# resolves_probe.find_probe_candidates (out_meta) +
# resolves_probe.emit_probe_status (probe_meta). Consumers: future
# divert classifier, retro analysis.
METADATA_KEY_PROBE_SNAPSHOT_MAX_TS = "probe_snapshot_max_ts"
METADATA_KEY_PROBE_TAIL_TS = "probe_tail_ts"

# Selector-signal vocabulary for resolves_probe._score_candidate. Each
# constant names a signal that contributed to a candidate's score and
# appears in the candidate's selection_reasons list iff that signal
# scored non-zero. Listed in the order _score_candidate emits them
# (deterministic for test assertions).
SELECTION_REASON_KEYWORD = "keyword"
SELECTION_REASON_FILE_OVERLAP = "file_overlap"
SELECTION_REASON_RECENCY = "recency"
SELECTION_REASON_CLOSE_MODE = "close_mode"
# Siblings axis: events from the same close-reviewer batch as a recent
# close event surface even without keyword/file overlap. Closes the
# probe-divert gap where in-batch siblings were missed because they had no
# file or keyword tie to the current commit.
SELECTION_REASON_IN_SPRINT_BATCH = "in_sprint_batch"
# Widening for batched close-mode siblings: when in_sprint_batch AND
# close_mode both fire and file_overlap is 0, score +1 and emit this
# reason. Targets the outside-file-domain divert observed at 33% of
# recent diverts (close-mode multi-resolves), where a legitimate
# sibling fell off the top-5 cap because file_overlap=0 starved its
# score. Tests for double-counting prevention live in
# TestInBatchCloseNoOverlapWidening.
SELECTION_REASON_IN_BATCH_CLOSE_NO_OVERLAP = "in_batch_close_no_overlap"

# Divert-reason vocabulary written by retro_metrics._classify_divert_reason
# into probe_divert_details[i]["reason"]. Each value names the cause class
# of an agent's resolves choice falling outside the probe candidate set,
# so retros can act on cause not just count. UNKNOWN is the catch-all so
# no divert is silently uncategorized. Order matches first-match precedence
# in the classifier. MISSING_EVENT and PROBE_SELECTION_MISS added by
# story-005 after sprint-065 retro flagged 8/8 diverts as 'unknown'
# (4/8 = rejected ID not in events.jsonl, 4/8 = in-domain probe miss).
DIVERT_REASON_MISSING_EVENT = "missing-event"
DIVERT_REASON_NEWER_THAN_SNAPSHOT = "newer-than-snapshot"
DIVERT_REASON_OUTSIDE_FILE_DOMAIN = "outside-file-domain"
DIVERT_REASON_CROSS_STORY = "cross-story"
DIVERT_REASON_WRONG_TYPE = "wrong-type"
DIVERT_REASON_PROBE_SELECTION_MISS = "probe-selection-miss"
# NO_CANDIDATES is a probe-level signal (the candidate set itself was
# empty), not an event-level miss. Bucketing here separates candidate-
# generation failures from ranking misses so retros can act on the
# right fix domain. Sprint-072 retro flagged 9 consecutive sub-50%
# adoption periods with diverts that were really empty-candidate cases
# misattributed as snapshot/selection misses.
DIVERT_REASON_NO_CANDIDATES = "no-candidates"
DIVERT_REASON_UNKNOWN = "unknown"

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

# Pre-commit probe status event contracts.
# Resolves-trailer probe (resolves_probe.emit_probe_status):
#   content f"{STATUS_CONTENT_RESOLVES_PROBE}: {N} candidates"
#   metadata {METADATA_KEY_PROBE_CANDIDATES: [ids]}
# Story-prefix probe (story_probe.emit_probe_status):
#   content f"{STATUS_CONTENT_STORY_PROBE}: {story_id}"
#   metadata {METADATA_KEY_STORY_CANDIDATE: story_id}
STATUS_CONTENT_RESOLVES_PROBE = "resolves_probe_shown"
STATUS_CONTENT_STORY_PROBE = "story_probe_shown"
METADATA_KEY_STORY_CANDIDATE = "story_candidate"

# Retrospective event metadata.action discriminators — distinguish session
# retros from sprint retros so the session-start watermark scanner only
# advances on session retros. Without this, a sprint retro at end of session
# poisons the next session's retro detection.
RETRO_ACTION_SESSION_DONE = "session_retro_done"
RETRO_ACTION_SPRINT_DONE = "sprint_retro_done"


MAX_JSON_ARG_SIZE = 65536
MAX_CONTENT_LENGTH = 50_000
MAX_EVENT_BYTES = 100_000
MAX_EVENTS_FILE_SIZE = 10_485_760  # 10 MB

CONTENT_BUDGETS: dict[str, int | None] = {
    EVENT_TYPE_STATUS: 200,
    EVENT_TYPE_COMMIT: None,
    EVENT_TYPE_DECISION: 400,
    EVENT_TYPE_CONVENTION: 250,
    EVENT_TYPE_CONCERN: 400,
    EVENT_TYPE_DEBT: 400,
    EVENT_TYPE_QUESTION: 450,
    EVENT_TYPE_ANSWER: 350,
    EVENT_TYPE_ASSUMPTION: 400,
    EVENT_TYPE_DISCOVERY: 400,
    EVENT_TYPE_GOAL: 200,
    EVENT_TYPE_CUSTOMER_INPUT: None,
    EVENT_TYPE_CUSTOMER_INTENT: 250,
    EVENT_TYPE_SPRINT: 200,
    EVENT_TYPE_RETROSPECTIVE: 100,
    EVENT_TYPE_SESSION_END: 50,
    EVENT_TYPE_SESSION_SUMMARY: 2000,
}


# Required fields — used by validate_event() and repair.py's fast issubset check
REQUIRED_FIELDS = frozenset({"id", "type", "ts", "agent_id", "content"})


# Event types with no type-specific validation beyond the universal
# REQUIRED_FIELDS and content-budget checks. Test gate:
# tests/engine/test_compact.py::TestEventTypeMatchCompleteness fails
# if a new EVENT_TYPE_* is added without either a `case` arm in
# validate_event or an entry here. Listing a type means the universal
# checks are sufficient — explicit declaration, not oversight.
_VALIDATE_NO_TYPE_RULES = frozenset(
    {
        EVENT_TYPE_ASSUMPTION,
        EVENT_TYPE_CUSTOMER_INPUT,
        EVENT_TYPE_GOAL,
        EVENT_TYPE_SESSION_SUMMARY,
    }
)


# ---------------------------------------------------------------------------
# Event validation (single source of truth for required-field checks)
# ---------------------------------------------------------------------------


def get_required_budget(event_type: str) -> int:
    """Return the content budget for `event_type` or raise ValueError.

    Use this at call sites where the budget MUST exist (production
    enforcement paths, tests with seeded fixtures). Pyright sees the
    `int` return so callers don't need a follow-up
    `assert budget is not None` after a `CONTENT_BUDGETS[<key>]` lookup.

    Raises ValueError when the event_type is unknown to the schema, OR
    when its registered budget is None (uncapped types like
    `customer_input` and `retrospective` — callers that demand a numeric
    budget cannot be satisfied by an uncapped type, so failing loud
    here is the right move).
    """
    if event_type not in CONTENT_BUDGETS:
        raise ValueError(f"unknown event_type {event_type!r}; not in CONTENT_BUDGETS")
    budget = CONTENT_BUDGETS[event_type]
    if budget is None:
        raise ValueError(f"event_type {event_type!r} has no content budget (None)")
    return budget


def validate_event(event: dict) -> list[str]:
    """Validate event structure. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    # Universal required fields
    for field in REQUIRED_FIELDS:
        if field not in event:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(event[field], str):
            errors.append(f"Field '{field}' must be a string")

    if errors:
        return errors  # Can't validate further without basics

    # Content length limit — prevent unbounded event growth
    if len(event["content"]) > MAX_CONTENT_LENGTH:
        errors.append(
            f"Field 'content' exceeds maximum length "
            f"({len(event['content'])} > {MAX_CONTENT_LENGTH})"
        )

    event_type = event["type"]
    if event_type not in VALID_TYPES:
        errors.append(f"Invalid event type: {event_type}")
        return errors

    # Per-type content budget
    budget = CONTENT_BUDGETS.get(event_type)
    if budget is not None and len(event["content"]) > budget:
        errors.append(
            f"Content exceeds {event_type} budget "
            f"({len(event['content'])} > {budget} chars). "
            f"Shorten to \u2264{budget} chars."
        )

    # Universal optional field types
    if "references" in event:
        if not isinstance(event["references"], list):
            errors.append("Field 'references' must be an array")
        elif not all(isinstance(r, str) for r in event["references"]):
            errors.append("Field 'references' items must be strings")
    if "metadata" in event:
        metadata = event["metadata"]
        if not isinstance(metadata, dict):
            errors.append("Field 'metadata' must be an object")
        elif METADATA_KEY_RESOLVES in metadata:
            resolves = metadata[METADATA_KEY_RESOLVES]
            if not isinstance(resolves, list):
                errors.append(
                    f"metadata.{METADATA_KEY_RESOLVES} must be a list of event IDs"
                    f" (got {type(resolves).__name__})"
                )
            else:
                for idx, item in enumerate(resolves):
                    if not isinstance(item, str):
                        errors.append(
                            f"metadata.{METADATA_KEY_RESOLVES}[{idx}] must be a string"
                            f" (got {type(item).__name__})"
                        )
                    elif not EVENT_ID_RE.match(item):
                        errors.append(
                            f"metadata.{METADATA_KEY_RESOLVES}[{idx}] must be a"
                            f" 12-char hex event ID (got {item!r})"
                        )
    if "schema_version" in event and not isinstance(event["schema_version"], int):
        errors.append("Field 'schema_version' must be an integer")

    # Type-specific validation
    match event_type:
        case "debt":
            if "files" not in event:
                errors.append("Field 'files' is required for type 'debt'")
            elif not isinstance(event["files"], list):
                errors.append("Field 'files' must be an array")
            elif not all(isinstance(f, str) for f in event["files"]):
                errors.append("Field 'files' items must be strings")

        case "customer_intent":
            if "intent_status" not in event:
                errors.append(
                    "Field 'intent_status' is required for type 'customer_intent'"
                )
            elif event["intent_status"] not in VALID_INTENT_STATUSES:
                errors.append(
                    f"Invalid intent_status: {event['intent_status']} "
                    f"(must be open/delivered/superseded)"
                )

        case "status":
            if "working_on" not in event:
                errors.append("Field 'working_on' is required for type 'status'")
            elif not isinstance(event["working_on"], list):
                errors.append("Field 'working_on' must be an array")

        case "decision" | "convention":
            if "topic" not in event:
                errors.append(f"Field 'topic' is required for type '{event_type}'")
            elif not isinstance(event["topic"], str):
                errors.append("Field 'topic' must be a string")
            elif event["topic"] == "retro-try-adopted":
                errors.append(
                    "Topic 'retro-try-adopted' is too generic — use"
                    " 'retro-try-<slug>' (e.g. 'retro-try-answer-recording')"
                )

        case "concern":
            if "severity" in event and event["severity"] not in VALID_SEVERITIES:
                errors.append(
                    f"Invalid severity: {event['severity']}"
                    f" (must be {'/'.join(sorted(VALID_SEVERITIES))})"
                )
            if "files" in event and not isinstance(event["files"], list):
                errors.append("Field 'files' must be an array")

        case "question":
            if "priority" not in event:
                errors.append("Field 'priority' is required for type 'question'")
            elif event["priority"] not in VALID_PRIORITIES:
                errors.append(
                    f"Invalid priority: {event['priority']}"
                    " (must be \U0001f534/\U0001f7e1/\U0001f7e2)"
                )

        case "commit":
            if "files" in event and not isinstance(event["files"], list):
                errors.append("Field 'files' must be an array")

        case "answer" | "discovery":
            # Both link to the event they react to (answer→question,
            # discovery→assumption-it-contradicts). Universal references
            # validation already checks list-of-strings; require non-empty.
            refs = event.get("references")
            if not refs:
                errors.append(
                    f"Field 'references' is required and must be non-empty "
                    f"for type '{event_type}'"
                )

        case "session_end":
            _check = {
                "duration_seconds": (int, float),
                "event_count": int,
                "unresolved_items": list,
                "working_on": list,
            }
            _labels = {
                (int, float): "a number",
                int: "an integer",
                list: "an array",
            }
            for _f, _t in _check.items():
                if _f in event and not isinstance(event[_f], _t):
                    errors.append(f"Field '{_f}' must be {_labels[_t]}")

        case "sprint":
            meta = event.get("metadata")
            if not isinstance(meta, dict):
                errors.append("Field 'metadata' is required for type 'sprint'")
            else:
                sprint_id = meta.get("sprint_id")
                if not sprint_id or not isinstance(sprint_id, str):
                    errors.append(
                        "Field 'metadata.sprint_id' is required and must be "
                        "a non-empty string for type 'sprint'"
                    )
                action = meta.get("action")
                if action not in VALID_SPRINT_ACTIONS:
                    errors.append(
                        f"Invalid metadata.action: {action} (must be start/end)"
                    )

        case "retrospective":
            for field in ("keep", "fix", "try"):
                if field in event:
                    if not isinstance(event[field], list):
                        errors.append(f"Field '{field}' must be an array")
                    else:
                        for i, item in enumerate(event[field]):
                            if not isinstance(item, dict):
                                errors.append(f"Field '{field}[{i}]' must be an object")
                            elif "content" not in item:
                                errors.append(
                                    f"Field '{field}[{i}].content' is required"
                                )

    return errors
