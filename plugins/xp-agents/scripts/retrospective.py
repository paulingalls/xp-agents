#!/usr/bin/env python3
"""SessionStart hook: prepare retrospective data for the analyst agent.

Checks for unanalyzed events since the last retrospective. If enough
have accumulated (≥5), writes .retro-input.json for the retrospective
analyst agent hook to consume. Always exits 0.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import sizing_metrics
from event_schema import (
    EVENT_TYPE_SPRINT,
    EVENT_TYPE_STATUS,
    RETRO_ACTION_SESSION_DONE,
    SPRINT_ACTION_END,
    SPRINT_ACTION_START,
    STATUS_ACTION_SPRINT_RETRO_DONE,
)
from honesty_signals import build_honesty_signals
from retro_history import annotate_try_status, gather_retro_history

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RETRO_THRESHOLD = 5
MAX_EVENTS_IN_RETRO = 200


# ---------------------------------------------------------------------------
# Sprint detection
# ---------------------------------------------------------------------------


def needs_sprint_retro(events: list[dict]) -> str | None:
    """Return the sprint_id that needs a retro, or None.

    A sprint retro is needed when:
    1. A sprint_end event exists (the most recent one).
    2. No sprint_retro_done status event has been recorded for that sprint_id.
    3. No newer sprint_start event exists (that would mean the user moved on
       without retro-ing the old sprint — session retro handles it).
    """
    end_index = -1
    end_sprint_id: str | None = None
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        if event.get("type") != EVENT_TYPE_SPRINT:
            continue
        metadata = event.get("metadata", {})
        if metadata.get("action") != SPRINT_ACTION_END:
            continue
        end_index = i
        end_sprint_id = metadata.get("sprint_id")
        break

    if end_sprint_id is None:
        return None

    for event in events[end_index + 1 :]:
        event_type = event.get("type")
        metadata = event.get("metadata", {})
        action = metadata.get("action")

        if event_type == EVENT_TYPE_SPRINT and action == SPRINT_ACTION_START:
            return None

        if (
            event_type == EVENT_TYPE_STATUS
            and action == STATUS_ACTION_SPRINT_RETRO_DONE
            and metadata.get("sprint_id") == end_sprint_id
        ):
            return None

    return end_sprint_id


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


# Signal event types — full event dicts preserved in digest
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

# Status classification patterns
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
    """Deduplicate unresolved concerns by normalized content.

    Resolved concerns are excluded — they're rolled up to a count
    in the digest instead. Returns {key, count, ids} — ids are short
    (8 chars) for housekeeping reference.
    """
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

# (event type, resolutions dict key) — ordered for deterministic output
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
    """Map target IDs to resolver event info for the retro digest.

    Each target ID lands in exactly one bucket — compute_resolutions uses
    a match/case on event type so a single ID cannot appear under multiple
    types.
    """
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
    """Build structured digest from unanalyzed events.

    Resolved concerns are excluded from signal_events and concern_groups
    and rolled up to a count — the retro doesn't need their full text.
    The full resolutions map (all 6 types) is exposed so the retro analyst
    can cross-reference previous Try items against this session's activity.
    """
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


def _find_unanalyzed_start(events: list[dict]) -> int:
    """Find the index of the first unanalyzed event (after last session retro).

    Only session retrospectives advance the watermark. Sprint retros are
    transparent — they don't mean "we reviewed these events for trends".
    Legacy retros without metadata.action default to session (backwards
    compat for pre-M1 event logs).

    Returns the start index. Unanalyzed count is len(events) - start.
    """
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        if event.get("type") != _common.RETROSPECTIVE:
            continue
        action = event.get("metadata", {}).get("action")
        if action is None or action == RETRO_ACTION_SESSION_DONE:
            return i + 1
    return 0


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

    for e in events:
        match e.get("type", ""):
            case _common.STATUS:
                stats["status_count"] += 1
                if e.get("metadata", {}).get("action") == "iteration_complete":
                    stats["iterations_completed"] += 1
            case _common.CONCERN:
                stats["concerns_raised"] += 1
            case _common.QUESTION:
                question_ids.add(e.get("id", ""))
            case _common.DECISION:
                stats["decisions_total"] += 1

    resolutions = resolution.compute_resolutions(events)
    stats["concerns_resolved"] = len(resolutions["resolved_concern_ids"])
    stats["questions_answered"] = len(resolutions["answered_question_ids"])
    answered = resolutions["answered_question_ids"]
    stats["questions_open"] = len(question_ids) - len(answered)

    return stats


def _build_retro_input(
    events: list[dict],
    start_idx: int,
    retro_history: list[dict],
) -> dict:
    """Build the .retro-input.json structure.

    Caps events_since_last_retro to MAX_EVENTS_IN_RETRO (most recent).
    """
    import resolution
    from retro_flags import evaluate_flags

    unanalyzed = events[start_idx:]
    type_counts = dict(Counter(e.get("type", "unknown") for e in unanalyzed))
    session_stats = _compute_session_stats(unanalyzed)
    resolutions = resolution.compute_resolutions(unanalyzed)
    digest = _build_retro_digest(events, start_idx, resolutions)
    annotate_try_status(retro_history, digest["resolutions"])

    decision_topics: list[str] = [
        topic
        for e in events
        if e.get("type") == _common.DECISION
        and isinstance((topic := e.get("topic")), str)
    ]

    digest["flags"] = evaluate_flags(
        digest["honesty_signals"],
        digest["work_signals"],
        digest["status_summary"],
        session_stats,
        decisions=decision_topics,
    )

    # Slim the digest for the subagent — reduce token cost
    # Signal events: keep only type, content, short id
    # Truncate customer_input (raw user prompts) and commit messages
    _MAX_CUSTOMER_INPUT = 100
    _MAX_COMMIT_CONTENT = 400
    if "signal_events" in digest:
        slimmed_signals = []
        for e in digest["signal_events"]:
            etype = e.get("type", "")
            content = e.get("content", "")
            if etype == _common.CUSTOMER_INPUT and len(content) > _MAX_CUSTOMER_INPUT:
                content = content[:_MAX_CUSTOMER_INPUT]
            elif etype == _common.COMMIT and len(content) > _MAX_COMMIT_CONTENT:
                content = content[:_MAX_COMMIT_CONTENT]
            slimmed_signals.append(
                {"type": etype, "content": content, "id": e.get("id", "")}
            )
        digest["signal_events"] = slimmed_signals
    return {
        "unanalyzed_count": len(unanalyzed),
        # No events_since_last_retro — digest has the structured version
        "previous_retros": retro_history,
        "event_type_counts": type_counts,
        "session_stats": session_stats,
        "digest": digest,
    }


def _write_retro_input(smm_dir: Path, data: dict) -> None:
    """Write .retro-input.json atomically via _common.write_json_atomic."""
    _common.write_json_atomic(smm_dir / _common.RETRO_INPUT_FILENAME, data)


def _build_context_summary(
    unanalyzed_count: int,
    type_counts: dict,
    session_stats: dict | None = None,
) -> str:
    """Build kickoff preparation context — counts and health only.

    No event details — those are for the retro subagent via .retro-input.json.
    """
    parts: list[str] = []

    # Header with stats
    parts.append(
        f"**Kickoff preparation complete.** "
        f"{unanalyzed_count} events from previous session ready for review."
    )
    if type_counts:
        summary = ", ".join(f"{count} {t}" for t, count in sorted(type_counts.items()))
        parts.append(f"Event breakdown: {summary}.")

    # Session health signals
    if session_stats:
        health: list[str] = []
        cr = session_stats.get("concerns_raised", 0)
        cres = session_stats.get("concerns_resolved", 0)
        if cr:
            health.append(f"Concerns: {cr} raised, {cres} resolved")
        dt = session_stats.get("decisions_total", 0)
        if dt:
            health.append(f"Decisions: {dt}")
        qo = session_stats.get("questions_open", 0)
        if qo:
            health.append(f"{qo} open questions")
        if health:
            parts.append("Health: " + "; ".join(health) + ".")

    # Direct to kickoff — don't analyze here
    parts.append(
        "\n\n---\n"
        "**ACTION REQUIRED:** Run /xp-kickoff to process this data. "
        "It handles retrospective, questions, goals, and housekeeping. "
        "Do NOT analyze these events yourself — the kickoff skill "
        "delegates to dedicated subagents."
    )
    return "\n".join(parts)


_PROBE_PREFIX = "resolves_probe_shown:"


def _compute_resolves_link_rate(
    events: list[dict], sprint_start_ts: str | None
) -> dict:
    """Compute resolves_link_rate from probe events vs. subsequent commit trailers.

    For each status event with content='resolves_probe_shown: N candidates',
    find the NEXT commit event by the same agent_id within the sprint window.
    A "hit" is when commit.metadata.resolves intersects probe.metadata.probe_candidates.

    Returns three fields: resolves_link_rate (float), resolves_probe_hits (int),
    resolves_probe_total (int). Rate is 0.0 when total is 0; caller decides
    whether to attach the fields at all.

    NOTE: "Next commit by same agent" is a best-effort pairing heuristic — a
    git commit --amend keeps the same working-tree logic but creates a new
    commit_hash, so pairing strictly by commit_hash would undercount. This
    heuristic accepts the first subsequent commit by the same agent as the
    candidate; future retros may refine this.
    """

    def _in_window(event: dict) -> bool:
        if sprint_start_ts is None:
            return True
        return event.get("ts", "")[:10] >= sprint_start_ts

    probes = [
        e
        for e in events
        if e.get("type") == _common.STATUS
        and e.get("content", "").startswith(_PROBE_PREFIX)
        and _in_window(e)
    ]

    hits = 0
    for probe in probes:
        candidates = set((probe.get("metadata") or {}).get("probe_candidates") or [])
        if not candidates:
            continue
        agent_id = probe.get("agent_id", "")
        probe_ts = probe.get("ts", "")
        for e in events:
            if e.get("type") != _common.COMMIT:
                continue
            if e.get("agent_id", "") != agent_id:
                continue
            if e.get("ts", "") <= probe_ts:
                continue
            resolves = set((e.get("metadata") or {}).get("resolves") or [])
            if resolves & candidates:
                hits += 1
            break

    total = len(probes)
    return {
        "resolves_link_rate": hits / total if total > 0 else 0.0,
        "resolves_probe_hits": hits,
        "resolves_probe_total": total,
    }


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core retrospective data preparation logic.

    Returns additionalContext string when retro is needed, None otherwise.
    """
    if _common.is_xp_agent(input_data):
        return None

    source = input_data.get("source", "")
    if source == "compact":
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_raw(smm_dir)

    sprint_id = needs_sprint_retro(events)

    start_idx = _find_unanalyzed_start(events)
    unanalyzed_count = len(events) - start_idx

    if unanalyzed_count < RETRO_THRESHOLD and sprint_id is None:
        return None

    retro_history = gather_retro_history(smm_dir)
    retro_input = _build_retro_input(events, start_idx, retro_history)

    if sprint_id is not None:
        sizing = sizing_metrics.compute_sizing_analysis(smm_dir, events)
        if sizing is not None:
            link_stats = _compute_resolves_link_rate(events, sizing.get("started"))
            if link_stats["resolves_probe_total"] > 0:
                sizing.update(link_stats)
            retro_input["sizing_analysis"] = sizing

    _write_retro_input(smm_dir, retro_input)

    (smm_dir / ".sprint-retro-input.json").unlink(missing_ok=True)

    return _build_context_summary(
        unanalyzed_count,
        retro_input["event_type_counts"],
        retro_input.get("session_stats"),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        _match = re.search(r"(\d+) (?:events|stories)", context)
        _count = _match.group(1) if _match else "some"
        _matched = _match.group(0) if _match else ""
        _label = "stories" if "stories" in _matched else "events"
        _common.hook_output(
            "SessionStart",
            context,
            f"Kickoff data prepared — {_count} {_label} to review.",
        )
    sys.exit(0)
