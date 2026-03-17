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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RETRO_THRESHOLD = 5
MAX_RETRO_HISTORY = 3
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
        _common.PAIR_GUIDANCE,
    }
)

# Status classification patterns
_FILE_WRITE_RE = re.compile(r"Wrote to\b", re.IGNORECASE)
_TEST_RUN_RE = re.compile(r"Tests?:.*\d+\s+passed", re.IGNORECASE)

_MAX_STATUS_SAMPLES = 10


def _normalize_concern_content(content: str) -> str:
    """Normalize content for dedup: replace digits, strip backtick-quoted."""
    normalized = re.sub(r"\d+", "N", content)
    normalized = re.sub(r"`[^`]*`", "``", normalized)
    return normalized.strip()


def _classify_status_events(
    events: list[dict],
) -> dict:
    """Classify status events into file_writes, test_runs, other."""
    file_writes: list[dict] = []
    test_runs: list[dict] = []
    other: list[dict] = []

    for e in events:
        if e.get("type") != _common.STATUS:
            continue
        content = e.get("content", "")
        if _FILE_WRITE_RE.search(content):
            file_writes.append(e)
        elif _TEST_RUN_RE.search(content):
            test_runs.append(e)
        else:
            other.append(e)

    total = len(file_writes) + len(test_runs) + len(other)
    return {
        "total": total,
        "file_writes": len(file_writes),
        "test_runs": len(test_runs),
        "other": len(other),
        "samples": {
            "file_writes": file_writes[-_MAX_STATUS_SAMPLES:],
            "test_runs": test_runs[-_MAX_STATUS_SAMPLES:],
            "other": other[-_MAX_STATUS_SAMPLES:],
        },
    }


def _group_concerns(events: list[dict]) -> list[dict]:
    """Deduplicate concerns by normalized content."""
    groups: dict[str, dict] = {}
    for e in events:
        if e.get("type") != _common.CONCERN:
            continue
        key = _normalize_concern_content(e.get("content", ""))
        if key not in groups:
            groups[key] = {"key": key, "count": 0, "events": []}
        groups[key]["count"] += 1
        groups[key]["events"].append(e)
    return list(groups.values())


def _build_retro_digest(events: list[dict], start_idx: int) -> dict:
    """Build structured digest from unanalyzed events."""
    unanalyzed = events[start_idx:]

    signal_events = [e for e in unanalyzed if e.get("type") in _SIGNAL_TYPES]
    status_summary = _classify_status_events(unanalyzed)
    concern_groups = _group_concerns(unanalyzed)

    return {
        "signal_events": signal_events,
        "status_summary": status_summary,
        "concern_groups": concern_groups,
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
    """Read the last N retrospective JSON files, sorted by filename desc."""
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
                result.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return result


def _compute_session_stats(events: list[dict]) -> dict:
    """Compute session statistics using shared resolution tracking."""
    import _append_impl

    stats = {
        "pair_guidance_count": 0,
        "status_count": 0,
        "concerns_raised": 0,
        "concerns_resolved": 0,
        "questions_open": 0,
        "questions_answered": 0,
        "decisions_total": 0,
        "decisions_draft": 0,
    }

    question_ids: set[str] = set()

    for e in events:
        match e.get("type", ""):
            case _common.PAIR_GUIDANCE:
                stats["pair_guidance_count"] += 1
            case _common.STATUS:
                stats["status_count"] += 1
            case _common.CONCERN:
                stats["concerns_raised"] += 1
            case _common.QUESTION:
                question_ids.add(e.get("id", ""))
            case _common.DECISION:
                stats["decisions_total"] += 1
                if e.get("metadata", {}).get("draft"):
                    stats["decisions_draft"] += 1

    resolutions = _append_impl.compute_resolutions(events)
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
    unanalyzed = events[start_idx:]
    type_counts = dict(Counter(e.get("type", "unknown") for e in unanalyzed))
    session_stats = _compute_session_stats(unanalyzed)
    digest = _build_retro_digest(events, start_idx)
    return {
        "unanalyzed_count": len(unanalyzed),
        "events_since_last_retro": unanalyzed[-MAX_EVENTS_IN_RETRO:],
        "previous_retros": retro_history,
        "event_type_counts": type_counts,
        "session_stats": session_stats,
        "digest": digest,
    }


def _write_retro_input(smm_dir: Path, data: dict) -> None:
    """Write .retro-input.json atomically via _common.write_json_atomic."""
    _common.write_json_atomic(smm_dir / ".retro-input.json", data)


def _summarize_key_events(events: list[dict]) -> str:
    """Produce a condensed text summary of non-status events for analysis."""
    lines: list[str] = []
    skip_types = {_common.STATUS, _common.SECURITY_REVIEW_REQUESTED}
    for e in events:
        etype = e.get("type", "")
        if etype in skip_types:
            continue
        eid = e.get("id", "?")[:8]
        content = e.get("content", "")
        if len(content) > 200:
            content = content[:200] + "..."
        lines.append(f"- [{etype}] ({eid}) {content}")
    return "\n".join(lines[-50:])  # cap at 50 most recent


def _build_context_summary(
    unanalyzed_count: int,
    type_counts: dict,
    session_stats: dict | None = None,
    key_events: list[dict] | None = None,
) -> str:
    """Build inline retrospective context with data and analysis instructions."""
    parts: list[str] = []

    # Header with stats
    parts.append(f"**Retrospective: {unanalyzed_count} unanalyzed events.**")
    if type_counts:
        summary = ", ".join(f"{count} {t}" for t, count in sorted(type_counts.items()))
        parts.append(f"Event breakdown: {summary}.")

    # Session health signals
    if session_stats:
        health: list[str] = []
        pg = session_stats.get("pair_guidance_count", 0)
        sc = session_stats.get("status_count", 0)
        if pg == 0 and sc > 5:
            health.append(f"CRITICAL: 0 navigator guidance with {sc} status events")
        elif pg:
            health.append(f"{pg} navigator guidance events")
        cr = session_stats.get("concerns_raised", 0)
        cres = session_stats.get("concerns_resolved", 0)
        if cr:
            health.append(f"Concerns: {cr} raised, {cres} resolved")
        dt = session_stats.get("decisions_total", 0)
        dd = session_stats.get("decisions_draft", 0)
        if dt:
            health.append(f"Decisions: {dt} total, {dd} still draft")
        qo = session_stats.get("questions_open", 0)
        if qo:
            health.append(f"{qo} open questions")
        if health:
            parts.append("Health: " + "; ".join(health) + ".")

    # Key events for analysis
    if key_events:
        event_summary = _summarize_key_events(key_events)
        if event_summary:
            parts.append(f"\nKey events:\n{event_summary}")

    # Inline K/F/T instructions
    parts.append(
        "\n\n---\n"
        "**ACTION REQUIRED:** Perform Keep/Fix/Try retrospective analysis "
        "before starting new work.\n\n"
        "Using the SMM context and event data above, analyze through XP values "
        "(Honesty, Communication, Courage, Simplicity, Respect):\n"
        "- **Keep**: What went well? Reference specific events.\n"
        "- **Fix**: What went wrong? Name the XP value violated.\n"
        "- **Try**: Concrete experiments for this session.\n\n"
        "Display the analysis to the user, then run /xp-retrospective "
        "to record results to the event log."
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

    return _build_context_summary(
        unanalyzed_count,
        retro_input["event_type_counts"],
        retro_input.get("session_stats"),
        retro_input.get("events_since_last_retro"),
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    context = run(input_data)
    if context is not None:
        _common.hook_output("SessionStart", context)
    sys.exit(0)
