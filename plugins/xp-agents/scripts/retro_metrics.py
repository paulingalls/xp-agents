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
import worktree
from event_schema import (
    DISPOSITION_DROPPED,
    DIVERT_REASON_CROSS_STORY,
    DIVERT_REASON_MISSING_EVENT,
    DIVERT_REASON_NEWER_THAN_SNAPSHOT,
    DIVERT_REASON_NO_CANDIDATES,
    DIVERT_REASON_OUTSIDE_FILE_DOMAIN,
    DIVERT_REASON_PROBE_SELECTION_MISS,
    DIVERT_REASON_UNKNOWN,
    DIVERT_REASON_WRONG_TYPE,
    METADATA_KEY_DISPOSITION,
    METADATA_KEY_RESOLVES,
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

# Resolves-eligible event types per the resolves probe contract: agents
# tag commits with concern/debt/discovery IDs. Used by
# _classify_divert_reason to flag wrong-type diverts.
_VALID_RESOLVES_TYPES = frozenset({_common.CONCERN, _common.DEBT, _common.DISCOVERY})

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
    re-proposing Trys the user has already rejected. Scans the FULL events
    list (not session-scoped) — prior-session drops MUST be visible.
    """
    drops = [
        {
            "id": e.get("id", ""),
            "ts": e.get("ts", ""),
            "content": e.get("content", "")[:_MAX_RESOLVER_CONTENT],
        }
        for e in events
        if e.get("type") == _common.STATUS
        and (e.get("metadata") or {}).get(METADATA_KEY_DISPOSITION)
        == DISPOSITION_DROPPED
        and (e.get("metadata") or {}).get(METADATA_KEY_RESOLVES)
    ]
    return sorted(drops, key=lambda d: d["ts"], reverse=True)[:limit]


def _build_retro_digest(events: list[dict], start_idx: int, resolutions: dict) -> dict:
    """Build structured digest. Most fields cover events[start_idx:] (the
    unanalyzed slice); `dropped_tries_recent` scans the FULL events list
    so prior-session drops remain visible across retros.
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
    cwd: str,
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

    probe_adoption = _compute_probe_adoption(
        events, code_commits, sprint_start_ts, cwd=cwd
    )

    return {
        "resolves_link_rate": total_hits / total if total > 0 else 0.0,
        "resolves_trailer_hits": total_hits,
        "resolves_trailer_total": total,
        "per_agent": per_agent,
        **probe_adoption,
    }


def _normalize_file_set(files: list[str], cwd: str) -> set[str]:
    """Canonicalize a list of file paths via worktree.normalize_path so
    './scripts/x.py', 'scripts/x.py', and absolute forms intersect on the
    same git-root-relative key. Mirrors resolves_probe._score_candidate
    and concerns.find_issues_for_file. Tests stub worktree.normalize_path
    (see TestFileOverlapNormalization) rather than skipping normalization.
    """
    out: set[str] = set()
    for f in files:
        if not isinstance(f, str):
            continue
        try:
            out.add(worktree.normalize_path(f, cwd))
        except (ValueError, OSError):
            continue
    return out


def _classify_divert_reason(
    rejected_event: dict,
    probe_ts: str,
    commit_files: list[str],
    story_id: str | None,
    cwd: str,
) -> str:
    """Reason an agent's resolves choice fell outside the probe candidate set.

    First-match precedence per story-006 reason table. The rule order is the
    contract — callers pin via test fixtures, so reordering here breaks them.
    DIVERT_REASON_UNKNOWN is the catch-all so no divert is silently
    uncategorized.

    Precedence (story-005 widened post sprint-065 retro): missing-event,
    newer-than-snapshot, outside-file-domain, cross-story, wrong-type,
    probe-selection-miss, unknown.

    File overlap normalizes both rejected_files and commit_files via
    worktree.normalize_path — mirrors the canonical pattern at
    resolves_probe._score_candidate so abs/rel/'./' forms match.

    cross-story is dormant in practice today (spike: 0/84
    concern/debt/discovery events carried metadata.story_id) but we
    keep the rule for forward-compat — once teammates start tagging, it
    lights up without a code change.
    """
    if not rejected_event:
        return DIVERT_REASON_MISSING_EVENT
    rejected_ts = rejected_event.get("ts") or ""
    if probe_ts and rejected_ts and rejected_ts > probe_ts:
        return DIVERT_REASON_NEWER_THAN_SNAPSHOT

    rejected_files = rejected_event.get("files") or []
    rejected_set = _normalize_file_set(rejected_files, cwd)
    commit_set = _normalize_file_set(commit_files, cwd)
    files_overlap = bool(rejected_set & commit_set)
    if (
        isinstance(rejected_files, list)
        and rejected_files
        and commit_files
        and not files_overlap
    ):
        return DIVERT_REASON_OUTSIDE_FILE_DOMAIN

    rejected_meta = rejected_event.get("metadata") or {}
    rejected_story = (
        rejected_meta.get("story_id") if isinstance(rejected_meta, dict) else None
    )
    if story_id and rejected_story and rejected_story != story_id:
        return DIVERT_REASON_CROSS_STORY

    if rejected_event.get("type") not in _VALID_RESOLVES_TYPES:
        return DIVERT_REASON_WRONG_TYPE

    # All exclusionary checks passed AND files clearly overlap → probe
    # should have surfaced this candidate but didn't. Sprint-065 retro
    # found 4/8 diverts in this shape, all previously bucketed UNKNOWN.
    # files_overlap=True implies both lists were non-empty (empty sets
    # can't intersect), so no need to re-check.
    if files_overlap:
        return DIVERT_REASON_PROBE_SELECTION_MISS

    return DIVERT_REASON_UNKNOWN


def _compute_probe_adoption(
    events: list[dict],
    code_commits: list[dict],
    sprint_start_ts: str | None,
    cwd: str,
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
        METADATA_KEY_PROBE_SELECTION_REASONS,
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
        "probe_divert_details": [],
    }
    if not probes:
        return zero

    sorted_probes = sorted(probes, key=lambda p: p.get("ts") or "")
    sorted_commits = sorted(code_commits, key=lambda c: c.get("ts") or "")
    consumed: set[int] = set()

    # Lookup map for divert reason classification: rejected resolves IDs
    # are looked up to inspect ts / files / metadata.story_id / type.
    events_by_id: dict[str, dict] = {eid: e for e in events if (eid := e.get("id"))}

    hits = 0
    escape = 0
    divert = 0
    silent = 0
    divert_details: list[dict] = []
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
        commit = sorted_commits[paired_index]
        resolves = (commit.get("metadata") or {}).get(METADATA_KEY_RESOLVES) or []
        if any(rid in candidate_ids for rid in resolves):
            hits += 1
        elif not resolves:
            escape += 1
        else:
            divert += 1
            reasons_map = (probe.get("metadata") or {}).get(
                METADATA_KEY_PROBE_SELECTION_REASONS
            ) or {}
            sorted_candidates = sorted(candidate_ids)
            if not candidate_ids:
                # Empty candidate set — root cause is candidate generation,
                # not ranking. The per-event classifier would inspect the
                # rejected event and return a misleading reason
                # (NEWER_THAN_SNAPSHOT, PROBE_SELECTION_MISS, etc.); skip
                # it and bucket as NO_CANDIDATES.
                reason = DIVERT_REASON_NO_CANDIDATES
            else:
                commit_files = commit.get("files") or []
                commit_story_id = (commit.get("metadata") or {}).get("story_id")
                # Single dominant reason per divert: multi-id diverts cluster on
                # one root cause in practice (almost all diverts are 1-id anyway).
                # Pick the latest-by-ts rejected event — semantically "the agent's
                # most recent context" — over alphabetic min() which is meaningless
                # for hex IDs. Missing events sort to the front (empty ts).
                picked_id = max(
                    resolves,
                    key=lambda rid: (events_by_id.get(rid) or {}).get("ts") or "",
                )
                rejected_event = events_by_id.get(picked_id) or {}
                reason = _classify_divert_reason(
                    rejected_event,
                    probe_ts=probe_ts,
                    commit_files=commit_files,
                    story_id=commit_story_id,
                    cwd=cwd,
                )
            divert_details.append(
                {
                    "agent_id": agent_id,
                    "probe_ts": probe_ts,
                    "commit_ts": commit.get("ts") or "",
                    "candidates": sorted_candidates,
                    "resolves": sorted(resolves),
                    "selection_reasons": {
                        cid: reasons_map.get(cid, []) for cid in sorted_candidates
                    },
                    "reason": reason,
                }
            )

    probe_total = len(probes)
    return {
        "probe_adoption_rate": hits / probe_total if probe_total > 0 else 0.0,
        "probe_adoption_hits": hits,
        "probe_adoption_total": probe_total,
        "probe_escape": escape,
        "probe_divert": divert,
        "probe_silent": silent,
        "probe_divert_details": divert_details,
    }
