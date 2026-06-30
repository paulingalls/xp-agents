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
import commits
import triage
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

# Canonical target for resolves_link_rate (the share of eligible code commits
# carrying a Resolves-Event trailer). Single source of truth for the 0.80
# threshold shared by two consumers: trailer_gate.advisory imports it as its
# pre-merge THRESHOLD, and the xp-retrospective agent flags resolves_link_rate
# below this as a Fix (agents/xp-retrospective.md §Resolution-Link Adoption).
# Keep all three in sync — test_trailer_gate pins the trailer_gate import and
# the agent-prose value against this constant.
RESOLVES_LINK_RATE_TARGET = 0.80

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

    # Cadence context for the retro agent: how many commits in the window
    # deferred their review to /xp-story-close. A low quality_reviews-to-commits
    # ratio is BY DESIGN when this is high (one cumulative review per story),
    # not a discipline gap. The deterministic quality_reviews_missing flag is
    # already suppressed for these commits; this surfaces the same fact to the
    # LLM prose so it doesn't editorialize a false "fewer reviews than commits".
    story_cadence_commits = sum(
        1
        for e in unanalyzed
        if e.get("type") == _common.COMMIT
        and (e.get("metadata") or {}).get("review_cadence") == "story"
    )

    return {
        "signal_events": signal_events,
        "status_summary": status_summary,
        "concern_groups": concern_groups,
        "honesty_signals": honesty_signals,
        "work_signals": work_sigs,
        "resolved_concern_count": len(resolved_concern_ids),
        "dropped_tries_recent": dropped_tries_recent,
        "security_close_ran": security_close_ran,
        "story_cadence_commits": story_cadence_commits,
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


def has_resolves_trailer(meta: dict) -> bool:
    """True when a commit's metadata signals a Resolves-Event trailer.

    Legacy events used has_resolves_trailer; current writers populate
    metadata.resolves directly. Either signals a numerator hit. The sole
    speaker of both shapes — reused by trailer_gate's pre-merge advisory so
    the gate and the retro score the numerator identically.
    """
    return bool(meta.get(METADATA_KEY_RESOLVES) or meta.get("has_resolves_trailer"))


def eligible_trailer_commits(
    events: list[dict],
    sprint_start_ts: str | None,
) -> list[dict]:
    """The candidate-gated denominator: code commits we'd expect to carry a
    Resolves-Event trailer.

    Extracted from _compute_resolves_link_rate so trailer_gate's pre-merge
    advisory reuses the EXACT same eligibility — a divergent candidate gate
    silently mis-scores (see the candidate-gate note below). Behavior is
    identical to the inlined filter it replaced.
    """

    # Candidate gate (the denominator's defining filter): only commits that, AT
    # COMMIT TIME, structurally overlapped an open concern/debt/question count.
    # A feature/refactor commit touching no tracked issue's files legitimately
    # carries no trailer and must not be scored a "miss" — counting all eligible
    # commits floored the rate near the fraction that happen to close a tracked
    # event (~1/3), making 0.80 unachievable. See
    # docs/completed/resolves-link-rate-denominator.md.
    #
    # "Open AT COMMIT TIME", not open-at-retro (triage.find_unresolved): a concern
    # closed by a commit's OWN trailer would drop from the open set, removing the
    # successful linker from the denominator and zeroing the rate for a perfect
    # sprint. We key on resolution TIMING (metadata.resolves) instead: an issue
    # stays a candidate for commit C while issue.ts < C.ts <= earliest-resolve-ts
    # (<= keeps the resolving commit itself a candidate). Reuses
    # triage.find_overlapping_commits (overlap + commit-after-issue) — no dup loop.
    issue_types = (_common.CONCERN, _common.DEBT, _common.QUESTION)
    resolve_ts: dict[str, str] = {}
    for ev in events:
        for rid in (ev.get("metadata") or {}).get(METADATA_KEY_RESOLVES) or []:
            ts = ev.get("ts", "")
            if rid not in resolve_ts or ts < resolve_ts[rid]:
                resolve_ts[rid] = ts
    candidate_ids: set[str] = set()
    for issue in events:
        if issue.get("type") not in issue_types or not issue.get("files"):
            continue
        issue_resolved_ts = resolve_ts.get(issue.get("id", ""))
        for commit in triage.find_overlapping_commits(issue, events):
            if issue_resolved_ts is None or commit.get("ts", "") <= issue_resolved_ts:
                candidate_ids.add(commit.get("id", ""))

    # Filter the denominator to "commits we'd expect to carry a Resolves
    # trailer". Exclusions, each for its own reason:
    #
    #   is_merge==True       — close-cycle merge HEAD; aggregates already-
    #                          counted story commits, no trailer of its own.
    #   escape-hatch message — [release]/[chore]/[sprint-direct] commits
    #                          bypass the review/resolution discipline by
    #                          design (version bump, CHANGELOG, chores); they
    #                          carry no meaningful trailer, same noise class
    #                          as merge HEADs (mirrors the honesty_signals
    #                          review-required exemption).
    #   story_id present     — bounded by the story (the story IS the unit
    #                          of resolution); story commits aren't expected
    #                          to carry trailers.
    #   is_free_session==True
    #     AND no trailer     — free-session exploration commit; nothing to
    #                          reference. Free commits WITH a trailer count
    #                          both ways (rewards the voluntary fix-and-link
    #                          behavior visibly — see Option B' in the
    #                          rate-denominator-fix free plan).
    #
    # NOTE: review_cadence=="story" is deliberately NOT an exclusion here —
    # the inverse of honesty_signals.review_required_commits, which DOES exempt
    # story-cadence commits. Cadence gates WHEN review happens; the trailer is
    # orthogonal — a non-story code commit closing a concern must link it
    # regardless of cadence. Story-mode story work is already excluded by
    # story_id above. Do not "consistency"-port the story-cadence exemption
    # pattern here; it would silently drop real commits and inflate the rate.
    # Pinned by test_retro_metrics.test_story_cadence_commit_without_story_id_included.
    def _included(e: dict) -> bool:
        if e.get("type") != _common.COMMIT:
            return False
        if not _event_in_sprint_window(e, sprint_start_ts):
            return False
        meta = e.get("metadata") or {}
        if not meta.get("code_commit"):
            return False
        if meta.get("is_merge"):
            return False
        if commits.is_escape_hatch_message(e.get("content")):
            return False
        if meta.get("story_id"):
            return False
        # Candidate gate: no open issue's files overlapped this commit at commit
        # time → nothing it should have linked → out of the denominator.
        if e.get("id") not in candidate_ids:
            return False
        # Free-session commits include conditionally: present-with-trailer
        # rewards voluntary fix-and-link; no-trailer is exploration.
        return not (meta.get("is_free_session") and not has_resolves_trailer(meta))

    return [e for e in events if _included(e)]


def _compute_resolves_link_rate(
    events: list[dict],
    sprint_start_ts: str | None,
) -> dict:
    """Count code commits with Resolves-Event trailers vs total code commits."""
    code_commits = eligible_trailer_commits(events, sprint_start_ts)

    total = len(code_commits)
    with_trailers = [
        e for e in code_commits if has_resolves_trailer(e.get("metadata") or {})
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
            1 for c in agent_commits if has_resolves_trailer(c.get("metadata") or {})
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
