#!/usr/bin/env python3
"""SessionStart hook: prepare retrospective data for the analyst agent.

Checks for unanalyzed events since the last retrospective. If enough
have accumulated (≥5), writes .retro-input.json for the retrospective
analyst agent hook to consume. Always exits 0.
"""

import json
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
    return {
        "unanalyzed_count": len(unanalyzed),
        "events_since_last_retro": unanalyzed[-MAX_EVENTS_IN_RETRO:],
        "previous_retros": retro_history,
        "event_type_counts": type_counts,
        "session_stats": session_stats,
    }


def _write_retro_input(smm_dir: Path, data: dict) -> None:
    """Write .retro-input.json atomically via _common.write_json_atomic."""
    _common.write_json_atomic(smm_dir / ".retro-input.json", data)


def _build_context_summary(
    unanalyzed_count: int,
    type_counts: dict,
    session_stats: dict | None = None,
) -> str:
    """Build a brief additionalContext string for the agent."""
    parts = [f"Retrospective data prepared: {unanalyzed_count} unanalyzed events."]
    if type_counts:
        summary = ", ".join(f"{count} {t}" for t, count in sorted(type_counts.items()))
        parts.append(f"Event breakdown: {summary}.")
    if session_stats:
        stat_items = []
        if session_stats.get("pair_guidance_count"):
            stat_items.append(
                f"{session_stats['pair_guidance_count']} navigator guidance"
            )
        if session_stats.get("concerns_raised"):
            stat_items.append(
                f"{session_stats['concerns_raised']} concerns "
                f"({session_stats.get('concerns_resolved', 0)} resolved)"
            )
        if session_stats.get("questions_open"):
            stat_items.append(f"{session_stats['questions_open']} open questions")
        if stat_items:
            parts.append(f"Key stats: {', '.join(stat_items)}.")
    parts.append("Read .retro-input.json from the SMM directory for full data.")
    parts.append(
        "\n\n---\n"
        "**ACTION REQUIRED:** Run /xp-retrospective NOW "
        "to perform Keep/Fix/Try analysis before starting any new work. "
        "Retrospectives surface cross-session learning and unresolved issues."
    )
    return " ".join(parts)


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
