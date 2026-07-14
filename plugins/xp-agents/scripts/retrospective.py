#!/usr/bin/env python3
"""SessionStart hook: prepare retrospective data for the analyst agent.

Checks for unanalyzed events since the last retrospective. If enough
have accumulated (>=5), writes .retro-input.json for the retrospective
analyst agent hook to consume. Always exits 0.

Metrics computation (session stats, status classification, digest building,
resolves link rate) lives in retro_metrics.py.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import _common
import marker_names
import session_history
import story_metrics
import tier_wire
from event_schema import (
    EVENT_TYPE_SPRINT,
    EVENT_TYPE_STATUS,
    RETRO_ACTION_SESSION_DONE,
    SPRINT_ACTION_END,
    SPRINT_ACTION_START,
    STATUS_ACTION_SPRINT_RETRO_DONE,
    event_action,
)
from retro_history import annotate_try_status, gather_retro_history
from retro_metrics import (
    _build_retro_digest,
    _compute_resolves_link_rate,
    _compute_session_stats,
    build_resolutions_map,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RETRO_THRESHOLD = 5

# Wire-contract action string for the tier-picker override audit trail (written
# by the xp-assign hand-off as a status event; the writer is shell and cannot
# import this, so this anchors the reader side).
_TIER_OVERRIDE_ACTION = tier_wire.TIER_OVERRIDE_ACTION


def _compute_tier_override_signal(events: list[dict]) -> dict:
    """Recommendation-acceptance signal for the retro agent's heuristic-accuracy
    analysis. Each tier_override status event is a rejected picker
    recommendation; a high ``override_count`` means the picker's recommendations
    are frequently overridden. No matching events -> count 0, empty list.
    """
    overrides = []
    for e in events:
        if e.get("type") != EVENT_TYPE_STATUS:
            continue
        if event_action(e) != _TIER_OVERRIDE_ACTION:
            continue
        md = e.get("metadata") or {}
        overrides.append(
            {
                "story_id": md.get("story_id", ""),
                "picked": md.get("picked", ""),
                "recommended": md.get("recommended", ""),
            }
        )
    return {"override_count": len(overrides), "overrides": overrides}


# ---------------------------------------------------------------------------
# Sprint detection
# ---------------------------------------------------------------------------


def needs_sprint_retro(events: list[dict]) -> str | None:
    """Return the sprint_id that needs a retro, or None."""
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
# Watermark
# ---------------------------------------------------------------------------


def _find_unanalyzed_start(events: list[dict]) -> int:
    """Find the index of the first unanalyzed event (after last session retro).

    Only session retrospectives advance the watermark. Sprint retros are
    transparent. Legacy retros without metadata.action default to session.
    """
    for i in range(len(events) - 1, -1, -1):
        event = events[i]
        if event.get("type") != _common.RETROSPECTIVE:
            continue
        action = event.get("metadata", {}).get("action")
        if action is None or action == RETRO_ACTION_SESSION_DONE:
            return i + 1
    return 0


# ---------------------------------------------------------------------------
# Retro input building
# ---------------------------------------------------------------------------


def _build_retro_input(
    events: list[dict],
    start_idx: int,
    retro_history: list[dict],
    resolutions: dict | None = None,
    recent_summaries: list[dict] | None = None,
    smm_dir: Path | None = None,
) -> dict:
    """Build the .retro-input.json structure.

    *recent_summaries* (when provided) carries the most recent
    session_history.json entries with pre-computed staleness, for
    cross-session pattern detection. Default ``[]`` keeps the field
    present so retro-agent prompts can rely on its existence.
    """
    import resolution
    from retro_flags import evaluate_flags

    if resolutions is None:
        resolutions = resolution.compute_resolutions(events)

    unanalyzed = events[start_idx:]
    type_counts = dict(Counter(e.get("type", "unknown") for e in unanalyzed))
    session_stats = _compute_session_stats(unanalyzed)
    digest = _build_retro_digest(events, start_idx, resolutions)

    annotate_try_status(
        retro_history, build_resolutions_map(resolutions), events, smm_dir
    )

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
        events=events,
    )
    digest["tier_override_signal"] = _compute_tier_override_signal(unanalyzed)

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
        "previous_retros": retro_history,
        "recent_summaries": recent_summaries or [],
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
    """Build kickoff preparation context -- counts and health only."""
    parts: list[str] = []

    parts.append(
        f"**Kickoff preparation complete.** "
        f"{unanalyzed_count} events from previous session ready for review."
    )
    if type_counts:
        summary = ", ".join(f"{count} {t}" for t, count in sorted(type_counts.items()))
        parts.append(f"Event breakdown: {summary}.")

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

    parts.append(
        "\n\n---\n"
        "**ACTION REQUIRED:** Run /xp-kickoff. "
        "Do NOT analyze these events yourself -- kickoff delegates "
        "to dedicated subagents."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(input_data: dict, smm_dir: Path | None = None) -> tuple[str, int] | None:
    """Core retrospective data preparation logic.

    Returns (additionalContext, unanalyzed_count) when retro is needed,
    None otherwise. The count is also embedded in the context prose, but
    callers needing the int (e.g. CLI systemMessage) get it directly to
    avoid regex round-tripping our own output.
    """
    if _common.is_xp_agent(input_data):
        return None

    source = input_data.get("source", "")
    if source == "compact":
        return None

    smm_dir = _common.get_validated_smm_dir(smm_dir)
    if smm_dir is None:
        return None

    events, resolutions = _common.load_events_with_resolutions(smm_dir)

    sprint_id = needs_sprint_retro(events)

    start_idx = _find_unanalyzed_start(events)
    unanalyzed_count = len(events) - start_idx

    if unanalyzed_count < RETRO_THRESHOLD and sprint_id is None:
        return None

    retro_history = gather_retro_history(smm_dir)
    recent_summaries = session_history.gather_recent_summaries(
        smm_dir,
        session_anchor_timestamps=session_history.filter_session_anchor_timestamps(
            events
        ),
    )
    retro_input = _build_retro_input(
        events, start_idx, retro_history, resolutions, recent_summaries, smm_dir
    )

    if sprint_id is not None:
        sizing = story_metrics.compute_story_analysis(smm_dir, events)
        if sizing is not None:
            link_stats = _compute_resolves_link_rate(events, sizing.get("started"))
            if link_stats["resolves_trailer_total"] > 0:
                link_per_agent = link_stats.pop("per_agent", {})
                sizing.update(link_stats)
                for agent_id, link_rate in link_per_agent.items():
                    sizing["per_agent"].setdefault(agent_id, {}).update(link_rate)
            retro_input["sizing_analysis"] = sizing

    _write_retro_input(smm_dir, retro_input)

    (smm_dir / marker_names.SPRINT_RETRO_INPUT).unlink(missing_ok=True)

    context = _build_context_summary(
        unanalyzed_count,
        retro_input["event_type_counts"],
        retro_input.get("session_stats"),
    )
    return context, unanalyzed_count


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    input_data = _common.read_hook_input()
    result = run(input_data)
    if result is not None:
        context, count = result
        _common.hook_output(
            "SessionStart",
            context,
            f"Kickoff data prepared -- {count} events to review.",
        )
    sys.exit(0)
