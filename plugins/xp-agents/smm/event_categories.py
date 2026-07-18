#!/usr/bin/env python3
"""Event type constants and event-category classification.

Split from event_schema.py for module size management (convention
91fcf9b8744d pattern — see event_metadata.py for the prior split of this
kind). Definitions live here; event_schema.py re-exports them by identity
so existing callers and `mock.patch("...event_schema.X")` sites keep
working unchanged.
"""

from enum import StrEnum

# ---------------------------------------------------------------------------
# Event type constants
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
