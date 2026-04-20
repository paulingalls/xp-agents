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
    METADATA_KEY_PROBE_CANDIDATES,
    METADATA_KEY_RESOLVES,
    STATUS_CONTENT_RESOLVES_PROBE,
)
from honesty_signals import build_honesty_signals

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

_FILE_WRITE_RE = re.compile(r"Wrote to\b", re.IGNORECASE)
_TEST_RUN_RE = _common.TEST_RUN_RE
_SECURITY_CHECK_RE = _common.SECURITY_CHECK_RE
_COMMIT_RE = _common.LEGACY_COMMIT_RE
_QUALITY_REVIEW_RE = re.compile(r"Quality review complete", re.IGNORECASE)
_LINT_RE = re.compile(r"Lint (?:errors? in|concern resolved)", re.IGNORECASE)


def _normalize_concern_content(content: str) -> str:
    """Normalize content for dedup: replace digits, strip backtick-quoted."""
    normalized = re.sub(r"\d+", "N", content)
    normalized = re.sub(r"`[^`]*`", "``", normalized)
    return normalized.strip()


def _classify_status_events(
    events: list[dict],
) -> dict:
    """Classify status events into file_writes, test_runs, other."""
    counts = {
        "file_writes": 0,
        "test_runs": 0,
        "security_checks": 0,
        "commits": 0,
        "quality_reviews": 0,
        "lint_events": 0,
        "other": 0,
    }

    patterns = [
        (_FILE_WRITE_RE, "file_writes"),
        (_TEST_RUN_RE, "test_runs"),
        (_SECURITY_CHECK_RE, "security_checks"),
        (_COMMIT_RE, "commits"),
        (_QUALITY_REVIEW_RE, "quality_reviews"),
        (_LINT_RE, "lint_events"),
    ]

    for e in events:
        if e.get("type") != _common.STATUS:
            continue
        content = e.get("content", "")
        matched = False
        for pattern, key in patterns:
            if pattern.search(content):
                counts[key] += 1
                matched = True
                break
        if not matched:
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


def _build_resolutions_map(resolutions: dict) -> dict[str, dict]:
    """Map target IDs to resolver event info for the retro digest."""
    result: dict[str, dict] = {}
    for type_name, bucket_key in _RESOLUTION_BUCKETS:
        for target_id, resolver in resolutions.get(bucket_key, {}).items():
            entry: dict = {
                "type": type_name,
                "resolver_id": resolver.get("id", ""),
                "resolver_content": resolver.get("content", "")[:_MAX_RESOLVER_CONTENT],
            }
            disposition = resolver.get("metadata", {}).get("disposition")
            if disposition:
                entry["disposition"] = disposition
            result[target_id] = entry
    return result


def _build_retro_digest(events: list[dict], start_idx: int, resolutions: dict) -> dict:
    """Build structured digest from unanalyzed events."""
    unanalyzed = events[start_idx:]
    resolved_concern_ids = resolutions.get("resolved_concern_ids", set())

    signal_events = [
        e
        for e in unanalyzed
        if e.get("type") in _SIGNAL_TYPES
        and not (
            e.get("type") == _common.CONCERN and e.get("id", "") in resolved_concern_ids
        )
    ]
    status_summary = _classify_status_events(unanalyzed)
    concern_groups = _group_concerns(unanalyzed, resolved_concern_ids)
    honesty_signals = build_honesty_signals(unanalyzed)

    from work_signals import build_work_signals

    work_sigs = build_work_signals(unanalyzed)

    return {
        "signal_events": signal_events,
        "status_summary": status_summary,
        "concern_groups": concern_groups,
        "honesty_signals": honesty_signals,
        "work_signals": work_sigs,
        "resolved_concern_count": len(resolved_concern_ids),
        "resolutions": _build_resolutions_map(resolutions),
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
                if e.get("metadata", {}).get("action") == "iteration_complete":
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


def _compute_resolves_link_rate(
    events: list[dict], sprint_start_ts: str | None
) -> dict:
    """Compute resolves_link_rate from probe events vs. subsequent commit trailers."""

    def _in_window(event: dict) -> bool:
        if sprint_start_ts is None:
            return True
        return event.get("ts", "")[:10] >= sprint_start_ts

    probes = [
        e
        for e in events
        if e.get("type") == _common.STATUS
        and e.get("content", "").startswith(f"{STATUS_CONTENT_RESOLVES_PROBE}:")
        and _in_window(e)
    ]

    per_agent_probes: dict[str, list[dict]] = {}
    for probe in probes:
        agent_id = probe.get("agent_id", "")
        per_agent_probes.setdefault(agent_id, []).append(probe)

    per_agent: dict[str, dict] = {}
    total_hits = 0
    for agent_id, agent_probes in per_agent_probes.items():
        agent_hits = 0
        for probe in agent_probes:
            candidates = set(
                (probe.get("metadata") or {}).get(METADATA_KEY_PROBE_CANDIDATES) or []
            )
            if not candidates:
                continue
            probe_ts = probe.get("ts", "")
            for e in events:
                if e.get("type") != _common.COMMIT:
                    continue
                if e.get("agent_id", "") != agent_id:
                    continue
                if e.get("ts", "") <= probe_ts:
                    continue
                resolves = set(
                    (e.get("metadata") or {}).get(METADATA_KEY_RESOLVES) or []
                )
                if resolves & candidates:
                    agent_hits += 1
                break
        agent_total = len(agent_probes)
        per_agent[agent_id] = {
            "resolves_link_rate": agent_hits / agent_total if agent_total > 0 else 0.0,
            "resolves_probe_hits": agent_hits,
            "resolves_probe_total": agent_total,
        }
        total_hits += agent_hits

    total = len(probes)
    return {
        "resolves_link_rate": total_hits / total if total > 0 else 0.0,
        "resolves_probe_hits": total_hits,
        "resolves_probe_total": total,
        "per_agent": per_agent,
    }
