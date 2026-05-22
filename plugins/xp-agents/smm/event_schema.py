#!/usr/bin/env python3
"""Event schema: type constants, validation rules, and field constraints.

Single source of truth for what constitutes a valid event. No I/O, no
file operations — pure validation logic and shared constants.

Extracted from _append_impl.py for module size management.
"""

import bisect
from enum import StrEnum

from smm_schema import EVENT_ID_RE

# ---------------------------------------------------------------------------
# Session aging utility
# ---------------------------------------------------------------------------


def sessions_since_event(anchor_timestamps: list[str], event_ts: str) -> int:
    """Count session boundary anchors that occurred after *event_ts*.

    Boundary anchors are ``session_started`` timestamps (the START of each
    session, including a mid-session ``/clear``). *anchor_timestamps* must
    be sorted ascending (ISO-8601 strings). Returns 0 when there are no
    anchors or the event is newer than all of them.
    """
    return len(anchor_timestamps) - bisect.bisect_right(anchor_timestamps, event_ts)


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
EVENT_TYPE_SESSION_STARTED = "session_started"
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
        EVENT_TYPE_SESSION_STARTED,
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
SPRINT_ACTION_VERIFY = "verify"
VALID_SPRINT_ACTIONS = frozenset(
    {SPRINT_ACTION_START, SPRINT_ACTION_END, SPRINT_ACTION_VERIFY}
)
VERIFY_STATUS_RED = "red"
VERIFY_STATUS_GREEN = "green"
VERIFY_STATUS_NONE = "none"
VALID_VERIFY_STATUSES = frozenset(
    {VERIFY_STATUS_RED, VERIFY_STATUS_GREEN, VERIFY_STATUS_NONE}
)
VALID_INTENT_STATUSES = frozenset({"open", "delivered", "superseded"})


# ---------------------------------------------------------------------------
# Event categories
# ---------------------------------------------------------------------------
# EVENT_CATEGORY classifies each EVENT_TYPE_* by where its data primarily
# lives and how the housekeeper treats it. Each type joins exactly one
# category. Adding a new EVENT_TYPE_* costs a single classification entry
# in _EVENT_CATEGORY_MAP — bucket/compact behavior follows automatically.
#
#   sibling_artifact — data lives primarily in another file or SMM pillar
#                      (commit→git log, retrospective→retros/*.json,
#                      sprint→sprint.json, session_end+summary→
#                      session_history.json, customer_intent→Intent,
#                      convention+decision→Constraints).
#   curation_pillar  — housekeeper buckets these as new signals each
#                      session OR they link (answer→question,
#                      discovery→assumption) to a bucketed type.
#   transient        — orchestration / no separate artifact / not curated
#                      (status, goal).
#
# The two derived allowlists below are NOT clean single-category unions —
# they're filter functions over the category mapping. See decision
# 3f738430c547: _VALIDATE_NO_TYPE_RULES stays an explicit orthogonal axis
# ("has type-specific validation rules" is not a category-shaped property).


class EVENT_CATEGORY(StrEnum):
    SIBLING_ARTIFACT = "sibling_artifact"
    CURATION_PILLAR = "curation_pillar"
    TRANSIENT = "transient"


# Categorization is anchored to materialize._bucket_new_events: CURATION_PILLAR =
# exactly the types bucketed as "new since last curation" (the housekeeper's
# new-signal inputs). Everything else is SIBLING_ARTIFACT (data lives elsewhere
# — pillar files, retros/*.json, sprint.json, session_history.json, the
# referenced question/assumption for answer/discovery) or TRANSIENT
# (orchestration, no separate artifact).
_EVENT_CATEGORY_MAP: dict[str, EVENT_CATEGORY] = {
    EVENT_TYPE_ANSWER: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_ASSUMPTION: EVENT_CATEGORY.CURATION_PILLAR,
    EVENT_TYPE_COMMIT: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_CONCERN: EVENT_CATEGORY.CURATION_PILLAR,
    EVENT_TYPE_CONVENTION: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_CUSTOMER_INPUT: EVENT_CATEGORY.CURATION_PILLAR,
    EVENT_TYPE_CUSTOMER_INTENT: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_DEBT: EVENT_CATEGORY.CURATION_PILLAR,
    EVENT_TYPE_DECISION: EVENT_CATEGORY.CURATION_PILLAR,
    EVENT_TYPE_DISCOVERY: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_GOAL: EVENT_CATEGORY.TRANSIENT,
    EVENT_TYPE_SESSION_STARTED: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_QUESTION: EVENT_CATEGORY.CURATION_PILLAR,
    EVENT_TYPE_RETROSPECTIVE: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_SESSION_END: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_SESSION_SUMMARY: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_SPRINT: EVENT_CATEGORY.SIBLING_ARTIFACT,
    EVENT_TYPE_STATUS: EVENT_CATEGORY.TRANSIENT,
}


def event_category_of(event_type: str) -> EVENT_CATEGORY:
    """Return the EVENT_CATEGORY for `event_type` or raise ValueError.

    Per the `_required` narrowing convention: callers know the type is
    valid (already passed validate_event), so we return EVENT_CATEGORY
    not Optional. Adding a new EVENT_TYPE_* without classifying it
    surfaces here loudly rather than silently dropping to a default
    bucket.
    """
    try:
        return _EVENT_CATEGORY_MAP[event_type]
    except KeyError as exc:
        raise ValueError(
            f"unknown event_type {event_type!r}; add to _EVENT_CATEGORY_MAP"
        ) from exc


# Re-exported from event_metadata (split-shim per convention 91fcf9b8744d
# when this file crossed 500 lines). Definitions live in event_metadata.py;
# callers keep using `event_schema.STATUS_ACTION_*` / `METADATA_KEY_*` /
# `DISPOSITION_*` / `RETRO_ACTION_*` / `event_action(...)` unchanged.
from event_metadata import (  # noqa: E402, F401
    CONCERN_KIND_CLOSE_CYCLE_BYPASS,
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    DISPOSITION_DROPPED,
    DISPOSITION_WONT_FIX,
    METADATA_KEY_CLOSE_CYCLE_ID,
    METADATA_KEY_CLOSE_MODE,
    METADATA_KEY_COMMIT_HASH,
    METADATA_KEY_DEFER_UNTIL,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_FLAGGED_STALE,
    METADATA_KEY_RESOLVED_BY_COMMITS,
    METADATA_KEY_RESOLVES,
    METADATA_KEY_STALE_SESSION_COUNT,
    METADATA_KEY_SUPERSEDES,
    METADATA_KEY_TDD_RED,
    RETRO_ACTION_SESSION_DONE,
    RETRO_ACTION_SPRINT_DONE,
    STATUS_ACTION_ASSIGN_COMPLETE,
    STATUS_ACTION_BASH_FAILED,
    STATUS_ACTION_CLOSE_STARTED,
    STATUS_ACTION_COMMIT_SUCCESS,
    STATUS_ACTION_CONCERN_CLASSIFY,
    STATUS_ACTION_END_SESSION_DROP,
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_HOUSEKEEPING_COMPLETE,
    STATUS_ACTION_ITERATION_COMPLETE,
    STATUS_ACTION_LINT_RESOLVED,
    STATUS_ACTION_PLAN_AWAITING_REVIEW,
    STATUS_ACTION_PLAN_COMPLETED,
    STATUS_ACTION_PLAN_EXITED,
    STATUS_ACTION_PLAN_REVIEWED,
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_QUESTION_CLOSE,
    STATUS_ACTION_SECURITY_COMPLETE,
    STATUS_ACTION_SIMPLIFY_COMPLETE,
    STATUS_ACTION_SPRINT_RETRO_DONE,
    STATUS_ACTION_SUBAGENT_COMPLETE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
    event_action,
)

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
    EVENT_TYPE_SESSION_STARTED: 50,
    EVENT_TYPE_CUSTOMER_INPUT: None,
    EVENT_TYPE_CUSTOMER_INTENT: 250,
    EVENT_TYPE_SPRINT: 200,
    EVENT_TYPE_RETROSPECTIVE: 100,
    EVENT_TYPE_SESSION_END: 50,
    EVENT_TYPE_SESSION_SUMMARY: 2000,
}


# Required fields — used by validate_event() and repair.py's fast issubset check
REQUIRED_FIELDS = frozenset({"id", "type", "ts", "agent_id", "content"})


_UNIVERSAL_KEYS = REQUIRED_FIELDS | frozenset(
    {"references", "metadata", "schema_version"}
)

# Allowed top-level keys per event type. Per-type extras MUST stay in
# sync with the `match event_type` arms in validate_event below — a new
# optional field needs entries in both places.
_TYPE_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    EVENT_TYPE_ANSWER: _UNIVERSAL_KEYS,
    EVENT_TYPE_ASSUMPTION: _UNIVERSAL_KEYS,
    EVENT_TYPE_COMMIT: _UNIVERSAL_KEYS | frozenset({"files"}),
    EVENT_TYPE_CONCERN: _UNIVERSAL_KEYS | frozenset({"files", "severity"}),
    EVENT_TYPE_CONVENTION: _UNIVERSAL_KEYS | frozenset({"topic"}),
    EVENT_TYPE_CUSTOMER_INPUT: _UNIVERSAL_KEYS,
    EVENT_TYPE_CUSTOMER_INTENT: _UNIVERSAL_KEYS | frozenset({"intent_status"}),
    EVENT_TYPE_DEBT: _UNIVERSAL_KEYS | frozenset({"files"}),
    EVENT_TYPE_DECISION: _UNIVERSAL_KEYS | frozenset({"topic"}),
    EVENT_TYPE_DISCOVERY: _UNIVERSAL_KEYS,
    EVENT_TYPE_GOAL: _UNIVERSAL_KEYS,
    EVENT_TYPE_SESSION_STARTED: _UNIVERSAL_KEYS,
    EVENT_TYPE_QUESTION: _UNIVERSAL_KEYS | frozenset({"priority"}),
    EVENT_TYPE_RETROSPECTIVE: _UNIVERSAL_KEYS | frozenset({"keep", "fix", "try"}),
    EVENT_TYPE_SESSION_END: _UNIVERSAL_KEYS
    | frozenset({"duration_seconds", "event_count", "unresolved_items", "working_on"}),
    EVENT_TYPE_SESSION_SUMMARY: _UNIVERSAL_KEYS,
    EVENT_TYPE_SPRINT: _UNIVERSAL_KEYS,
    EVENT_TYPE_STATUS: _UNIVERSAL_KEYS | frozenset({"working_on"}),
}


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
        EVENT_TYPE_SESSION_STARTED,
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

    allowed = _TYPE_ALLOWED_KEYS[event_type]
    if not event.keys() <= allowed:
        extras_str = ", ".join(repr(k) for k in sorted(event.keys() - allowed))
        errors.append(f"Unknown field(s) for type '{event_type}': {extras_str}")

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
                        f"Invalid metadata.action: {action} (must be start/end/verify)"
                    )
                elif (
                    action == SPRINT_ACTION_VERIFY
                    and meta.get("verify_status") not in VALID_VERIFY_STATUSES
                ):
                    errors.append(
                        "Field 'metadata.verify_status' is required and must "
                        "be red/green/none for action 'verify'"
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
