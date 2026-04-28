#!/usr/bin/env python3
"""Event schema: type constants, validation rules, and field constraints.

Single source of truth for what constitutes a valid event. No I/O, no
file operations — pure validation logic and shared constants.

Extracted from _append_impl.py for module size management.
"""

import bisect

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

# Cross-module metadata keys. Centralized here so producer and consumer
# cannot drift on the spelling.
#   METADATA_KEY_RESOLVES       — STRONG resolution link: event IDs this
#                                 event closes. Written by bash_post_tool,
#                                 concerns, and work_selection_decide;
#                                 read by pre_tool_bash, retrospective,
#                                 materialize, resolution.
#   METADATA_KEY_COMMIT_HASH    — git HEAD hash recorded on commit events
#                                 (bash_post_tool.py).
#   METADATA_KEY_PROBE_CANDIDATES — ids surfaced by the resolves-trailer
#                                 probe; paired with the status-content
#                                 discriminator below.
METADATA_KEY_RESOLVES = "resolves"
METADATA_KEY_COMMIT_HASH = "commit_hash"
METADATA_KEY_PROBE_CANDIDATES = "probe_candidates"
METADATA_KEY_DISPOSITION = "disposition"

# Retro Try disposition values written to metadata.disposition by
# work_selection_decide (adopt/defer/drop) and read by retro_history,
# subagent_start. Centralized to prevent producer/consumer drift.
DISPOSITION_ADOPTED = "adopted"
DISPOSITION_DEFERRED = "deferred"
DISPOSITION_DROPPED = "dropped"

# Resolves-trailer probe status event contract.
# Producer (resolves_probe.emit_probe_status, called from pre_tool_bash)
# emits content f"{STATUS_CONTENT_RESOLVES_PROBE}: {N} candidates" with
# metadata {METADATA_KEY_PROBE_CANDIDATES: [ids]}.
STATUS_CONTENT_RESOLVES_PROBE = "resolves_probe_shown"

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
}


# Required fields — used by validate_event() and repair.py's fast issubset check
REQUIRED_FIELDS = frozenset({"id", "type", "ts", "agent_id", "content"})


# ---------------------------------------------------------------------------
# Event validation (single source of truth for required-field checks)
# ---------------------------------------------------------------------------


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
    if "metadata" in event and not isinstance(event["metadata"], dict):
        errors.append("Field 'metadata' must be an object")
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
