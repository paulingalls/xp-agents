#!/usr/bin/env python3
"""Retention POLICY for log compaction: what survives, and for how long.

Split from `compact.py` (split-shim convention 91fcf9b8744d) when that module
crossed 500 lines. The seam is policy vs mechanism:

  * this module answers "which events must the log keep?" — pure functions over
    a list of event dicts, no IO, no locks, no clock.
  * `compact.py` owns the mechanism — the lock, the archive write, the atomic
    replace, the watermark bookkeeping. It imports DOWN into this module and
    re-exports every name here by identity, so `compact.X is
    compact_retention.X` and existing importers (and their mocks) keep working.

Two retention questions live here, and they age differently:

  * SMM-REFERENCED (`_collect_smm_referenced_ids`) — an event is pinned while
    the SMM still points at it (an unresolved concern, a young decision). It is
    a per-event question.
  * INDEX/CAP-BASED (`_classify_pre_watermark`) — the last N of a kind survive
    regardless of what points at them (anchors, retrospectives, sprint ends).
    It is a per-KIND question, and it ranks by FILE POSITION, never by a parsed
    id or timestamp.
"""

import event_schema as es
import resolution
import session_history

_DECISION_MAX_AGE = 3  # Sessions before unresolved decisions can compact
_ASSUMPTION_MAX_AGE = 5  # Sessions before unresolved assumptions/questions can compact

# Event types intentionally NOT collected by _collect_smm_referenced_ids.
# Derived from EVENT_CATEGORY with two named-set overrides:
#   - TRANSIENT types EXCEPT goal (goal is retained as a cross-session
#     intent marker even though it's not curated).
#   - SESSION_END + SESSION_SUMMARY: sibling_artifact types with separate
#     index-based retention (session_history.json holds the last 3
#     summaries; events.jsonl drops them).
#   - SESSION_STARTED: session-boundary anchor sibling_artifact, classified
#     here so the completeness gate is satisfied. Milestone 2 (boundary
#     re-anchor) must confirm anchors survive compaction for sessions_since
#     counting — same retention question session_end faces.
#   - ANSWER + DISCOVERY + CUSTOMER_INPUT: their lifecycle is tied to a
#     referenced event (answer→question, discovery→assumption) or they're
#     superseded by another type (customer_input→customer_intent). Not
#     SMM-referenced on their own, so they compact away.
# Test gate: tests/engine/test_compact.py::TestEventTypeMatchCompleteness
# fails if a new EVENT_TYPE_* lacks a `case` arm here AND isn't covered
# by the derivation below.
_COMPACT_INDEX_RETENTION_TYPES = frozenset(
    {
        es.EVENT_TYPE_SESSION_END,
        es.EVENT_TYPE_SESSION_SUMMARY,
        es.EVENT_TYPE_SESSION_STARTED,
    }
)
_COMPACT_REFERENCE_TIED_TYPES = frozenset(
    {es.EVENT_TYPE_ANSWER, es.EVENT_TYPE_DISCOVERY, es.EVENT_TYPE_CUSTOMER_INPUT}
)
# goal is TRANSIENT but kept as a cross-session intent marker.
_COMPACT_RETAINED_TRANSIENT_TYPES = frozenset({es.EVENT_TYPE_GOAL})
_COMPACT_INTENTIONALLY_ABSENT = frozenset(
    t
    for t in es.VALID_TYPES
    if (
        (
            es.event_category_of(t) == es.EVENT_CATEGORY.TRANSIENT
            and t not in _COMPACT_RETAINED_TRANSIENT_TYPES
        )
        or t in _COMPACT_INDEX_RETENTION_TYPES
        or t in _COMPACT_REFERENCE_TIED_TYPES
    )
)


def _compute_pending_retro_sprint_ids(events: list[dict]) -> set[str]:
    """Sprint IDs started but with no sprint_retro_done event yet.

    Includes both active sprints (no sprint_end) and ended-but-not-retro'd
    sprints. Their commit events must stay in events.jsonl so the eventual
    /xp-sprint-review can compute per-story metrics.
    """
    started: set[str] = set()
    retro_done: set[str] = set()
    for e in events:
        meta = e.get("metadata") or {}
        sid = meta.get("sprint_id")
        if not sid:
            continue
        etype = e.get("type")
        if (
            etype == es.EVENT_TYPE_SPRINT
            and meta.get("action") == es.SPRINT_ACTION_START
        ):
            started.add(sid)
        elif (
            etype == es.EVENT_TYPE_STATUS
            and meta.get("action") == es.STATUS_ACTION_SPRINT_RETRO_DONE
        ):
            retro_done.add(sid)
    return started - retro_done


def _collect_smm_referenced_ids(events: list[dict]) -> set[str]:
    """Collect IDs of events that are still active in the SMM.

    Active = unresolved goals, decisions/assumptions/questions (< 3 sessions old),
    conventions, unresolved concerns/debt, open customer_intents, sprint_starts
    of pending-retro sprints, and commits whose sprint_id is pending-retro
    (so /xp-sprint-review can compute per-story metrics).
    Retrospectives kept via separate retention logic (last 2).
    """
    resolutions = resolution.compute_resolutions(events)
    referenced: set[str] = set()

    # Build session boundary anchors (session_started) for decision aging.
    # Sort is required — sessions_since_event uses bisect_right on this list.
    anchor_timestamps = session_history.filter_session_anchor_timestamps(events)

    pending_retro_sprint_ids = _compute_pending_retro_sprint_ids(events)

    for event in events:
        eid = event.get("id", "")
        if not eid:
            continue
        etype = event.get("type", "")

        match etype:
            case es.EVENT_TYPE_GOAL:
                if eid not in resolutions["resolved_goal_ids"]:
                    referenced.add(eid)
            case es.EVENT_TYPE_DECISION:
                if eid in resolutions["resolved_decision_ids"]:
                    continue
                # Age-based: keep for _DECISION_MAX_AGE sessions
                decision_ts = event.get("ts", "")
                sessions_after = es.sessions_since_event(anchor_timestamps, decision_ts)
                if sessions_after < _DECISION_MAX_AGE:
                    referenced.add(eid)
            case es.EVENT_TYPE_CONVENTION:
                referenced.add(eid)
            case es.EVENT_TYPE_CONCERN:
                if eid not in resolutions["resolved_concern_ids"]:
                    referenced.add(eid)
            case es.EVENT_TYPE_DEBT:
                if eid not in resolutions["resolved_debt_ids"]:
                    referenced.add(eid)
            case es.EVENT_TYPE_QUESTION:
                if eid in resolutions["answered_question_ids"]:
                    continue
                # Age-based: compact unanswered questions
                q_ts = event.get("ts", "")
                q_sessions = es.sessions_since_event(anchor_timestamps, q_ts)
                if q_sessions < _ASSUMPTION_MAX_AGE:
                    referenced.add(eid)
            case es.EVENT_TYPE_CUSTOMER_INTENT:
                intent_status = event.get("intent_status", "open")
                if intent_status == "open":
                    referenced.add(eid)
            case es.EVENT_TYPE_ASSUMPTION:
                if eid in resolutions["resolved_assumption_ids"]:
                    continue
                # Age-based: compact unresolved assumptions
                a_ts = event.get("ts", "")
                a_sessions = es.sessions_since_event(anchor_timestamps, a_ts)
                if a_sessions < _ASSUMPTION_MAX_AGE:
                    referenced.add(eid)
            case es.EVENT_TYPE_SPRINT:
                meta = event.get("metadata", {})
                action = meta.get("action", "")
                sprint_id = meta.get("sprint_id", "")
                # Sprint starts retained until retro_done fires — keeps
                # _compute_pending_retro_sprint_ids able to identify the
                # sprint across multiple compaction rounds. Sprint ends
                # handled by index-based retention below.
                if (
                    action == es.SPRINT_ACTION_START
                    and sprint_id in pending_retro_sprint_ids
                ):
                    referenced.add(eid)
            case es.EVENT_TYPE_RETROSPECTIVE:
                # Keep last 2 for trend detection. _find_unanalyzed_start
                # needs the most recent as a watermark. Full archive in
                # retrospectives/ dir. Handled below with keep_retro_indices.
                pass
            case es.EVENT_TYPE_COMMIT:
                sid = (event.get("metadata") or {}).get("sprint_id")
                if sid and sid in pending_retro_sprint_ids:
                    referenced.add(eid)

    return referenced


def _classify_pre_watermark(
    pre_watermark: list[dict],
    all_events: list[dict],
    smm_ids: set[str],
) -> tuple[list[dict], list[dict], int]:
    """Classify pre-watermark events as retained or archived.

    Retention rules (checked in order):
    1. Last 3 session_end + last 3 session_started events (aging anchors)
    2. Last 2 retrospective events (for trend detection)
    3. Last 1 sprint end event (for velocity data)
    4. sprint_retro_done status events paired with retained sprint_end
       (so needs_sprint_retro detection stays correct after compaction)
    5. SMM-referenced events (unresolved goals, active decisions, etc.)
    6. Everything else → archived

    Returns (retained, archived, smm_ref_count).
    """
    # Find last 3 session_end events from pre-watermark. Retained for the
    # session_end summary/history readers (main still emits session_end with
    # the summary payload); the session_started block below is the live
    # aging anchor.
    pre_session_ends = [
        i
        for i, e in enumerate(pre_watermark)
        if e.get("type") == es.EVENT_TYPE_SESSION_END
    ]
    keep_session_end_indices = set(pre_session_ends[-3:])

    # Find last 3 session_started events from pre-watermark. These are the
    # Milestone 2 aging anchor — sessions_since_event counts them. They MUST
    # survive compaction or every aging count collapses to 0 (re-anchor inert).
    pre_session_starts = [
        i
        for i, e in enumerate(pre_watermark)
        if e.get("type") == es.EVENT_TYPE_SESSION_STARTED
    ]
    keep_session_started_indices = set(pre_session_starts[-3:])

    # Keep last 2 retro events across ALL events (not just pre-watermark).
    # Post-watermark retros count toward the cap so we don't accumulate 3+.
    all_retro_ids = [
        e.get("id", "")
        for e in all_events
        if e.get("type") == es.EVENT_TYPE_RETROSPECTIVE
    ]
    keep_retro_ids = set(all_retro_ids[-2:])
    pre_retro_indices = {
        i
        for i, e in enumerate(pre_watermark)
        if e.get("type") == es.EVENT_TYPE_RETROSPECTIVE
        and e.get("id", "") in keep_retro_ids
    }

    # Keep last 1 sprint end event across ALL events (velocity data).
    # Post-watermark sprint ends count toward the cap.
    def _is_sprint_end(e: dict) -> bool:
        return (
            e.get("type") == es.EVENT_TYPE_SPRINT
            and e.get("metadata", {}).get("action") == es.SPRINT_ACTION_END
        )

    all_sprint_end_ids = [e.get("id", "") for e in all_events if _is_sprint_end(e)]
    keep_sprint_end_ids = set(all_sprint_end_ids[-1:])
    pre_sprint_end_indices = {
        i
        for i, e in enumerate(pre_watermark)
        if _is_sprint_end(e) and e.get("id", "") in keep_sprint_end_ids
    }

    # Keep sprint_retro_done events whose sprint_id matches a retained
    # sprint_end. Sprint-id-paired rule keeps detection correct after
    # compaction — needs_sprint_retro would otherwise re-fire on a
    # retained sprint_end whose paired retro_done was archived.
    retained_sprint_ids: set[str] = set()
    for e in all_events:
        if _is_sprint_end(e) and e.get("id", "") in keep_sprint_end_ids:
            sid = e.get("metadata", {}).get("sprint_id")
            if sid:
                retained_sprint_ids.add(sid)

    def _is_paired_retro_done(e: dict) -> bool:
        if e.get("type") != es.EVENT_TYPE_STATUS:
            return False
        metadata = e.get("metadata") or {}
        return (
            metadata.get("action") == es.STATUS_ACTION_SPRINT_RETRO_DONE
            and metadata.get("sprint_id") in retained_sprint_ids
        )

    pre_retro_done_indices = {
        i for i, e in enumerate(pre_watermark) if _is_paired_retro_done(e)
    }

    retained: list[dict] = []
    archived: list[dict] = []
    smm_ref_count = 0

    for i, event in enumerate(pre_watermark):
        eid = event.get("id", "")

        if (
            i in keep_session_end_indices
            or i in keep_session_started_indices
            or i in pre_retro_indices
            or i in pre_sprint_end_indices
            or i in pre_retro_done_indices
        ):
            retained.append(event)
            continue

        if eid in smm_ids:
            retained.append(event)
            smm_ref_count += 1
            continue

        archived.append(event)

    return retained, archived, smm_ref_count
