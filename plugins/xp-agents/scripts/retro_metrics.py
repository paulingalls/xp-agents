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
from event_schema import METADATA_KEY_RESOLVES
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
_QUALITY_REVIEW_RE = _common.QUALITY_REVIEW_RE
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


def build_resolutions_map(resolutions: dict) -> dict[str, dict]:
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


def _event_in_sprint_window(event: dict, sprint_start_ts: str | None) -> bool:
    if sprint_start_ts is None:
        return True
    return event.get("ts", "")[:10] >= sprint_start_ts


def _compute_resolves_link_rate(
    events: list[dict], sprint_start_ts: str | None
) -> dict:
    """Count code commits with Resolves-Event trailers vs total code commits.

    Also computes probe_adoption_rate: when a probe was shown, how often
    did any code commit resolve one of the probe's candidate IDs?
    """

    code_commits = [
        e
        for e in events
        if e.get("type") == _common.COMMIT
        and _event_in_sprint_window(e, sprint_start_ts)
        and (e.get("metadata") or {}).get("code_commit")
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

    probe_adoption = _compute_probe_adoption(events, code_commits, sprint_start_ts)

    return {
        "resolves_link_rate": total_hits / total if total > 0 else 0.0,
        "resolves_trailer_hits": total_hits,
        "resolves_trailer_total": total,
        "per_agent": per_agent,
        **probe_adoption,
    }


def _compute_probe_adoption(
    events: list[dict],
    code_commits: list[dict],
    sprint_start_ts: str | None,
) -> dict:
    """Probe adoption: pair each probe with the next code commit by the
    same agent_id in the sprint window, then classify into hit / escape /
    divert / silent.

    - hit: paired commit's metadata.resolves contains a probe candidate id
    - escape: paired commit's metadata.resolves is empty (Resolves-Event: none)
    - divert: paired commit's metadata.resolves is non-empty but no overlap
    - silent: no paired commit (probe fired but no commit by same agent followed)
    """
    from event_schema import (
        METADATA_KEY_PROBE_CANDIDATES,
        STATUS_CONTENT_RESOLVES_PROBE,
    )

    probes = [
        e
        for e in events
        if e.get("type") == _common.STATUS
        and _event_in_sprint_window(e, sprint_start_ts)
        and (e.get("content") or "").startswith(STATUS_CONTENT_RESOLVES_PROBE)
    ]

    zero = {
        "probe_adoption_rate": 0.0,
        "probe_adoption_hits": 0,
        "probe_adoption_total": 0,
        "probe_escape": 0,
        "probe_divert": 0,
        "probe_silent": 0,
    }
    if not probes:
        return zero

    sorted_probes = sorted(probes, key=lambda p: p.get("ts") or "")
    sorted_commits = sorted(code_commits, key=lambda c: c.get("ts") or "")
    consumed: set[int] = set()

    hits = 0
    escape = 0
    divert = 0
    silent = 0
    for probe in sorted_probes:
        agent_id = probe.get("agent_id")
        probe_ts = probe.get("ts") or ""
        candidate_ids = set(
            (probe.get("metadata") or {}).get(METADATA_KEY_PROBE_CANDIDATES) or []
        )
        # Each probe consumes its own next-by-agent commit; two probes by the
        # same agent before a single commit must NOT both claim that commit.
        paired_index = next(
            (
                i
                for i, c in enumerate(sorted_commits)
                if i not in consumed
                and c.get("agent_id") == agent_id
                and (c.get("ts") or "") > probe_ts
            ),
            None,
        )
        if paired_index is None:
            silent += 1
            continue
        consumed.add(paired_index)
        resolves = (sorted_commits[paired_index].get("metadata") or {}).get(
            METADATA_KEY_RESOLVES
        ) or []
        if any(rid in candidate_ids for rid in resolves):
            hits += 1
        elif not resolves:
            escape += 1
        else:
            divert += 1

    probe_total = len(probes)
    return {
        "probe_adoption_rate": hits / probe_total if probe_total > 0 else 0.0,
        "probe_adoption_hits": hits,
        "probe_adoption_total": probe_total,
        "probe_escape": escape,
        "probe_divert": divert,
        "probe_silent": silent,
    }
