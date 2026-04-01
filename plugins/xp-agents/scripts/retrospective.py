#!/usr/bin/env python3
"""SessionStart hook: prepare retrospective data for the analyst agent.

Checks for unanalyzed events since the last retrospective. If enough
have accumulated (≥5), writes .retro-input.json for the retrospective
analyst agent hook to consume. Always exits 0.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _common
import security

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RETRO_THRESHOLD = 5
MAX_RETRO_HISTORY = 2
MAX_EVENTS_IN_RETRO = 200
_MAX_RETRO_FILE_SIZE = 1_048_576  # 1 MB


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


# Signal event types — full event dicts preserved in digest
_SIGNAL_TYPES = frozenset(
    {
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
_TEST_RUN_RE = re.compile(
    r"Tests?(?::.*\d+\s+passed|\s+passed|\s+ran\b)", re.IGNORECASE
)
_SECURITY_TRIAGE_RE = re.compile(r"Security triage (?:complete|started)", re.IGNORECASE)
_COMMIT_RE = re.compile(r"^Committed:", re.IGNORECASE)
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
        "security_triages": 0,
        "commits": 0,
        "quality_reviews": 0,
        "lint_events": 0,
        "other": 0,
    }

    patterns = [
        (_FILE_WRITE_RE, "file_writes"),
        (_TEST_RUN_RE, "test_runs"),
        (_SECURITY_TRIAGE_RE, "security_triages"),
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
        groups[key]["ids"].append(e.get("id", "")[:8])
    return list(groups.values())


def _build_honesty_signals(events: list[dict]) -> dict:
    """Analyze event sequence for honesty red flags.

    Looks at ordering and gaps, not just counts — gives the retro
    concrete data to reason about instead of inferring from totals.
    """
    signals: dict = {}

    # Track sequence for gap analysis
    writes_since_last_test = 0
    max_writes_without_test = 0
    commits_without_triage = 0
    total_commits = 0
    last_triage_seen = False
    concern_count = 0
    assumption_count = 0
    file_write_count = 0

    for e in events:
        etype = e.get("type", "")
        content = e.get("content", "")

        if etype == _common.STATUS:
            if _FILE_WRITE_RE.search(content):
                path = content.replace("Wrote to ", "").strip()
                if security.is_code_file(path):
                    file_write_count += 1
                    # TDD streak: only production code writes count
                    # (writing test files isn't a testing gap)
                    from pre_tool_write import is_test_file

                    if not is_test_file(path):
                        writes_since_last_test += 1
            elif _TEST_RUN_RE.search(content):
                max_writes_without_test = max(
                    max_writes_without_test, writes_since_last_test
                )
                writes_since_last_test = 0
            elif _SECURITY_TRIAGE_RE.search(content):
                last_triage_seen = True
            elif _COMMIT_RE.search(content):
                total_commits += 1
                if not last_triage_seen:
                    commits_without_triage += 1
                last_triage_seen = False  # consumed by this commit
        elif etype == _common.CONCERN:
            concern_count += 1
        elif etype == _common.ASSUMPTION:
            assumption_count += 1

    # Final streak (writes after last test)
    max_writes_without_test = max(max_writes_without_test, writes_since_last_test)

    signals["max_writes_without_test"] = max_writes_without_test
    signals["commits_without_triage"] = commits_without_triage
    signals["total_commits"] = total_commits

    # Complexity vs scrutiny: many writes but no concerns = uncritical?
    signals["code_file_writes"] = file_write_count
    signals["concerns_raised"] = concern_count
    signals["assumptions_stated"] = assumption_count

    # Final status check — was the last status event before session_end?
    has_final_status = False
    for e in reversed(events):
        if e.get("type") == "session_end":
            continue
        if e.get("type") == _common.STATUS:
            has_final_status = True
        break
    signals["final_status_recorded"] = has_final_status

    return signals


def _build_retro_digest(
    events: list[dict], start_idx: int, resolved_concern_ids: set[str]
) -> dict:
    """Build structured digest from unanalyzed events.

    Resolved concerns are excluded from signal_events and concern_groups
    and rolled up to a count — the retro doesn't need their full text.
    """
    unanalyzed = events[start_idx:]

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
    honesty_signals = _build_honesty_signals(unanalyzed)

    return {
        "signal_events": signal_events,
        "status_summary": status_summary,
        "concern_groups": concern_groups,
        "honesty_signals": honesty_signals,
        "resolved_concern_count": len(resolved_concern_ids),
    }


def _find_unanalyzed_start(events: list[dict]) -> int:
    """Find the index of the first unanalyzed event (after last retro).

    Returns the start index. Unanalyzed count is len(events) - start.
    """
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("type") == _common.RETROSPECTIVE:
            return i + 1
    return 0


def _gather_retro_history(smm_dir: Path, limit: int = MAX_RETRO_HISTORY) -> list[dict]:
    """Read the last N retrospective JSON files, slimmed to content only.

    Strips event_refs, values, xp_value — the retro agent only needs
    the content strings for trend detection (recurring fixes, adopted tries).
    """
    retro_dir = smm_dir / "retrospectives"
    if not retro_dir.is_dir():
        return []

    files = sorted(retro_dir.glob("*.json"), reverse=True)
    result: list[dict] = []
    for f in files[:limit]:
        try:
            if f.stat().st_size > _MAX_RETRO_FILE_SIZE:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Slim: keep only content strings from each item
                slimmed: dict = {}
                if "timestamp" in data:
                    slimmed["timestamp"] = data["timestamp"]
                for field in ("keep", "fix", "try"):
                    items = data.get(field, [])
                    slimmed[field] = [
                        item.get("content", item) if isinstance(item, dict) else item
                        for item in items
                    ]
                result.append(slimmed)
        except (json.JSONDecodeError, OSError):
            continue
    return result


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
    }

    question_ids: set[str] = set()

    for e in events:
        match e.get("type", ""):
            case _common.STATUS:
                stats["status_count"] += 1
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

    unanalyzed = events[start_idx:]
    type_counts = dict(Counter(e.get("type", "unknown") for e in unanalyzed))
    session_stats = _compute_session_stats(unanalyzed)
    resolutions = resolution.compute_resolutions(unanalyzed)
    resolved_concern_ids = resolutions.get("resolved_concern_ids", set())
    digest = _build_retro_digest(events, start_idx, resolved_concern_ids)

    # Slim the digest for the subagent — reduce token cost
    # Signal events: keep only type, content, short id
    # Truncate customer_input (raw user prompts) to 100 chars
    _MAX_CUSTOMER_INPUT = 100
    if "signal_events" in digest:
        slimmed_signals = []
        for e in digest["signal_events"]:
            etype = e.get("type", "")
            content = e.get("content", "")
            if etype == _common.CUSTOMER_INPUT and len(content) > _MAX_CUSTOMER_INPUT:
                content = content[:_MAX_CUSTOMER_INPUT]
            slimmed_signals.append(
                {"type": etype, "content": content, "id": e.get("id", "")[:8]}
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
    _common.write_json_atomic(smm_dir / ".retro-input.json", data)


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


def run(input_data: dict, smm_dir: Path | None = None) -> str | None:
    """Core retrospective data preparation logic.

    Returns additionalContext string when retro is needed, None otherwise.
    """
    if _common.is_xp_agent(input_data):
        return None

    source = input_data.get("source", "")
    if source == "compact":
        return None

    if smm_dir is None:
        smm_dir = _common.resolve_smm_dir()
    smm_dir = _common.try_validate_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events = _common.read_events_raw(smm_dir)
    start_idx = _find_unanalyzed_start(events)
    unanalyzed_count = len(events) - start_idx

    if unanalyzed_count < RETRO_THRESHOLD:
        return None

    retro_history = _gather_retro_history(smm_dir)
    retro_input = _build_retro_input(events, start_idx, retro_history)
    _write_retro_input(smm_dir, retro_input)

    # Main agent gets counts + health only — no event details.
    # The retro subagent reads .retro-input.json for the full data.
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
        _match = re.search(r"(\d+) events", context)
        _count = _match.group(1) if _match else "some"
        _common.hook_output(
            "SessionStart",
            context,
            f"Kickoff data prepared — {_count} events to review.",
        )
    sys.exit(0)
