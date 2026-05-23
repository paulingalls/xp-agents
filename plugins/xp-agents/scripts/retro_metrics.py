#!/usr/bin/env python3
"""Retrospective metrics computation: session stats, status classification,
digest building, and resolves link rate.

Pure computation — no I/O, no side effects. Called by retrospective.py.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
from event_schema import (
    DISPOSITION_DROPPED,
    METADATA_KEY_CLOSE_MODE,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_RESOLVES,
    STATUS_ACTION_CLOSE_STARTED,
    STATUS_ACTION_FILE_WRITE,
    STATUS_ACTION_ITERATION_COMPLETE,
    STATUS_ACTION_LINT_RESOLVED,
    STATUS_ACTION_QR_COMPLETE,
    STATUS_ACTION_SECURITY_COMPLETE,
    STATUS_ACTION_SIMPLIFY_COMPLETE,
    STATUS_ACTION_TEST_RUN_COMPLETE,
    event_action,
)
from honesty_signals import build_honesty_signals

# Security-bearing close modes — only these run Step 4 /security-review.
# Story-close skips Step 4 (sprint-close covers it via cumulative diff),
# so a story-close session MUST NOT flip security_close_ran.
_SECURITY_CLOSE_MODES = frozenset({"sprint", "free", "plan"})

# ---------------------------------------------------------------------------
# Signal event types — full event dicts preserved in digest
# ---------------------------------------------------------------------------

_SIGNAL_TYPES = frozenset(
    {
        _common.COMMIT,
        _common.CUSTOMER_INPUT,
        _common.DECISION,
        _common.CONCERN,
        _common.GOAL,
        _common.DEBT,
        _common.DISCOVERY,
        _common.QUESTION,
        _common.ANSWER,
        _common.ASSUMPTION,
        _common.CONVENTION,
    }
)

# ---------------------------------------------------------------------------
# Status classification
# ---------------------------------------------------------------------------

# Action-based dispatch for lifecycle events. Hook is the canonical producer;
# consumers read metadata.action exactly so LLM-authored content drift cannot
# zero the counters. STATUS_ACTION_BASH_FAILED has no counter — failures
# surface via concerns. Commits are counted via type=commit (handled by the
# early branch in the loop), not by STATUS_ACTION_COMMIT_SUCCESS.
_ACTION_TO_COUNTER: dict[str, str] = {
    STATUS_ACTION_SIMPLIFY_COMPLETE: "simplifies",
    STATUS_ACTION_QR_COMPLETE: "quality_reviews",
    STATUS_ACTION_SECURITY_COMPLETE: "security_checks",
    STATUS_ACTION_FILE_WRITE: "file_writes",
    STATUS_ACTION_TEST_RUN_COMPLETE: "test_runs",
    STATUS_ACTION_LINT_RESOLVED: "lint_events",
}


def _normalize_concern_content(content: str) -> str:
    """Normalize content for dedup: replace digits, strip backtick-quoted."""
    normalized = re.sub(r"\d+", "N", content)
    normalized = re.sub(r"`[^`]*`", "``", normalized)
    return normalized.strip()


def _classify_lifecycle_events(
    events: list[dict],
) -> dict:
    """Classify lifecycle events (status + commit) into counter buckets.

    Commit events tick the commits counter via the early type=commit branch;
    status events dispatch on metadata.action via _ACTION_TO_COUNTER.
    Unactioned status events → 'other'.
    """
    counts = {
        "file_writes": 0,
        "test_runs": 0,
        "security_checks": 0,
        "commits": 0,
        "quality_reviews": 0,
        "simplifies": 0,
        "lint_events": 0,
        "other": 0,
    }

    for e in events:
        etype = e.get("type", "")
        # type=commit is the canonical commit signal; counted before the
        # status guard so a real commit always ticks the commits counter.
        if etype == _common.COMMIT:
            counts["commits"] += 1
            continue
        if etype != _common.STATUS:
            continue

        action = event_action(e)
        action_counter = _ACTION_TO_COUNTER.get(action) if action else None
        if action_counter:
            counts[action_counter] += 1
        else:
            counts["other"] += 1

    counts["total"] = sum(counts.values())
    return counts


def _group_concerns(
    events: list[dict], resolved_ids: set[str] | None = None
) -> list[dict]:
    """Deduplicate unresolved concerns by normalized content."""
    if resolved_ids is None:
        resolved_ids = set()
    groups: dict[str, dict] = {}
    for e in events:
        if e.get("type") != _common.CONCERN:
            continue
        if e.get("id", "") in resolved_ids:
            continue
        key = _normalize_concern_content(e.get("content", ""))
        if key not in groups:
            groups[key] = {"key": key, "count": 0, "ids": []}
        groups[key]["count"] += 1
        groups[key]["ids"].append(e.get("id", ""))
    return list(groups.values())


_MAX_RESOLVER_CONTENT = 200

_RESOLUTION_BUCKETS = (
    (_common.CONCERN, "concern_resolutions"),
    (_common.DEBT, "debt_resolutions"),
    (_common.GOAL, "goal_resolutions"),
    (_common.QUESTION, "question_answers"),
    (_common.ASSUMPTION, "assumption_resolutions"),
    (_common.DECISION, "decision_resolutions"),
    ("other", "other_resolutions"),
)


def build_resolutions_map(resolutions: dict) -> dict[str, dict]:
    """Map target IDs to resolver event info for the retro digest."""
    result: dict[str, dict] = {}
    for type_name, bucket_key in _RESOLUTION_BUCKETS:
        for target_id, resolver in resolutions.get(bucket_key, {}).items():
            entry: dict = {
                "type": type_name,
                "resolver_id": resolver.get("id", ""),
                "resolver_type": resolver.get("type", ""),
                "resolver_content": resolver.get("content", "")[:_MAX_RESOLVER_CONTENT],
            }
            disposition = resolver.get("metadata", {}).get(METADATA_KEY_DISPOSITION)
            if disposition:
                entry["disposition"] = disposition
            result[target_id] = entry
    return result


def _collect_dropped_tries_recent(events: list[dict], limit: int = 10) -> list[dict]:
    """Last `limit` status-drop events with non-empty metadata.resolves.

    Surfaces cross-session drop memory to the retro agent so it can avoid
    re-proposing Trys the user has already rejected. Iterates in reverse
    file order and stops once `limit` matches are collected. Returned
    entries are in reverse file-order, not strictly ts-descending —
    event_builder assigns `ts` before the flock in append_event, so under
    concurrent writers two events can land in the file out of ts order
    (microsecond-millisecond skew). Acceptable here because the use case
    is "recent drops the user already rejected," not exact ordering.
    """
    drops: list[dict] = []
    for e in reversed(events):
        if e.get("type") != _common.STATUS:
            continue
        meta = e.get("metadata") or {}
        if meta.get(METADATA_KEY_DISPOSITION) != DISPOSITION_DROPPED:
            continue
        if not meta.get(METADATA_KEY_RESOLVES):
            continue
        drops.append(
            {
                "id": e.get("id", ""),
                "ts": e.get("ts", ""),
                "content": e.get("content", "")[:_MAX_RESOLVER_CONTENT],
            }
        )
        if len(drops) >= limit:
            break
    return drops


def _build_retro_digest(events: list[dict], start_idx: int, resolutions: dict) -> dict:
    """Build structured digest. Most fields cover events[start_idx:] (the
    unanalyzed slice); `dropped_tries_recent` reverse-scans the FULL events
    list (with an early-break at its limit) so prior-session drops remain
    visible across retros without paying for a full-history scan.
    """
    unanalyzed = events[start_idx:]
    resolved_concern_ids = resolutions.get("resolved_concern_ids", set())
    resolved_debt_ids = resolutions.get("resolved_debt_ids", set())

    signal_events = [
        e
        for e in unanalyzed
        if e.get("type") in _SIGNAL_TYPES
        and not (
            e.get("type") == _common.CONCERN and e.get("id", "") in resolved_concern_ids
        )
        and not (e.get("type") == _common.DEBT and e.get("id", "") in resolved_debt_ids)
    ]
    status_summary = _classify_lifecycle_events(unanalyzed)
    concern_groups = _group_concerns(unanalyzed, resolved_concern_ids)
    honesty_signals = build_honesty_signals(unanalyzed)
    dropped_tries_recent = _collect_dropped_tries_recent(events)
    security_close_ran = any(
        event_action(e) == STATUS_ACTION_CLOSE_STARTED
        and (e.get("metadata") or {}).get(METADATA_KEY_CLOSE_MODE)
        in _SECURITY_CLOSE_MODES
        for e in unanalyzed
    )

    from work_signals import build_work_signals

    work_sigs = build_work_signals(unanalyzed)

    return {
        "signal_events": signal_events,
        "status_summary": status_summary,
        "concern_groups": concern_groups,
        "honesty_signals": honesty_signals,
        "work_signals": work_sigs,
        "resolved_concern_count": len(resolved_concern_ids),
        "dropped_tries_recent": dropped_tries_recent,
        "security_close_ran": security_close_ran,
        "resolutions": build_resolutions_map(resolutions),
    }


# ---------------------------------------------------------------------------
# Session statistics
# ---------------------------------------------------------------------------


def _new_agent_stats() -> dict:
    return {
        "status_count": 0,
        "concerns_raised": 0,
        "decisions_total": 0,
    }


def _compute_session_stats(events: list[dict]) -> dict:
    """Compute session statistics using shared resolution tracking."""
    import resolution

    stats = {
        "status_count": 0,
        "concerns_raised": 0,
        "concerns_resolved": 0,
        "questions_open": 0,
        "questions_answered": 0,
        "decisions_total": 0,
        "iterations_completed": 0,
    }

    question_ids: set[str] = set()
    per_agent: dict[str, dict] = {}

    for e in events:
        agent_id = e.get("agent_id", "main")
        agent = per_agent.setdefault(agent_id, _new_agent_stats())
        match e.get("type", ""):
            case _common.STATUS:
                stats["status_count"] += 1
                agent["status_count"] += 1
                if event_action(e) == STATUS_ACTION_ITERATION_COMPLETE:
                    stats["iterations_completed"] += 1
            case _common.CONCERN:
                stats["concerns_raised"] += 1
                agent["concerns_raised"] += 1
            case _common.QUESTION:
                question_ids.add(e.get("id", ""))
            case _common.DECISION:
                stats["decisions_total"] += 1
                agent["decisions_total"] += 1

    resolutions = resolution.compute_resolutions(events)
    stats["concerns_resolved"] = len(resolutions["resolved_concern_ids"])
    stats["questions_answered"] = len(resolutions["answered_question_ids"])
    answered = resolutions["answered_question_ids"]
    stats["questions_open"] = len(question_ids) - len(answered)

    return {**stats, "per_agent": per_agent}


# ---------------------------------------------------------------------------
# Resolves link rate
# ---------------------------------------------------------------------------


def _event_in_sprint_window(event: dict, sprint_start_ts: str | None) -> bool:
    if sprint_start_ts is None:
        return True
    return event.get("ts", "")[:10] >= sprint_start_ts


def _compute_resolves_link_rate(
    events: list[dict],
    sprint_start_ts: str | None,
) -> dict:
    """Count code commits with Resolves-Event trailers vs total code commits."""

    # Exclude merge commits (metadata.is_merge==True): a close-cycle merge
    # HEAD aggregates already-counted story commits and its message has no
    # Resolves trailer of its own — counting it in the denominator dilutes
    # the rate without a meaningful numerator. See close_common
    # ._append_merge_commit_event for the marker source.
    code_commits = [
        e
        for e in events
        if e.get("type") == _common.COMMIT
        and _event_in_sprint_window(e, sprint_start_ts)
        and (e.get("metadata") or {}).get("code_commit")
        and not (e.get("metadata") or {}).get("is_merge")
    ]

    total = len(code_commits)
    with_trailers = [
        e
        for e in code_commits
        if (e.get("metadata") or {}).get(METADATA_KEY_RESOLVES)
        or (e.get("metadata") or {}).get("has_resolves_trailer")
    ]
    total_hits = len(with_trailers)

    per_agent_commits: dict[str, list[dict]] = {}
    for c in code_commits:
        agent_id = c.get("agent_id", "main")
        per_agent_commits.setdefault(agent_id, []).append(c)

    per_agent: dict[str, dict] = {}
    for agent_id, agent_commits in per_agent_commits.items():
        agent_total = len(agent_commits)
        agent_hits = sum(
            1
            for c in agent_commits
            if (c.get("metadata") or {}).get(METADATA_KEY_RESOLVES)
            or (c.get("metadata") or {}).get("has_resolves_trailer")
        )
        per_agent[agent_id] = {
            "resolves_link_rate": agent_hits / agent_total if agent_total > 0 else 0.0,
            "resolves_trailer_hits": agent_hits,
            "resolves_trailer_total": agent_total,
        }

    return {
        "resolves_link_rate": total_hits / total if total > 0 else 0.0,
        "resolves_trailer_hits": total_hits,
        "resolves_trailer_total": total,
        "per_agent": per_agent,
    }
