#!/usr/bin/env python3
"""Scan events.jsonl for unresolved debts, concerns, and questions.

Outputs formatted triage sections for the xp-work-selection preload.
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import commits  # noqa: E402
import event_schema  # noqa: E402
import intent  # noqa: E402
import materialize  # noqa: E402
import resolution  # noqa: E402
import session_history  # noqa: E402
import triage  # noqa: E402


def _format_intent(entry: dict, session_anchor_timestamps: list[str]) -> str:
    """Render one triage intent as a suffix on the item's line.

    ANNOTATE, never filter. An adopted or deferred item stays OPEN and stays
    OFFERED — dropping it from the list is indistinguishable, to the reader, from
    the item having been fixed, which is the laundering this milestone exists to
    end. What the user needs is the memory: you already said you'd do this.
    """
    if entry["intent"] == event_schema.DISPOSITION_DEFERRED:
        return f" — DEFERRED x{entry['defer_count']}"
    age = event_schema.sessions_since_event(
        session_anchor_timestamps, entry.get("intent_ts", "")
    )
    ago = "this session" if age == 0 else f"{age} session{'s' if age != 1 else ''} ago"
    return f" — ADOPTED ({ago}, by {entry.get('intent_by', '')})"


def format_triage_section(
    header: str,
    items: list[dict],
    session_anchor_timestamps: list[str],
    *,
    commit_overlap: dict[str, list[dict]] | None = None,
    intents: dict[str, dict] | None = None,
) -> str:
    """Format a triage section with aging info, plus any recorded triage intent.

    `intents` maps event id → the intent recorded about it (see smm/intent.py).
    Items carrying one are annotated, NOT removed — see `_format_intent`.
    """
    if not items:
        return ""
    lines = [f"### {header}:"]
    for item in items:
        event_id = item.get("id", "")
        age = event_schema.sessions_since_event(
            session_anchor_timestamps, item.get("ts", "")
        )
        age_str = f"{age} sessions" if age != 1 else "1 session"
        suffix = ""
        if intents and (entry := intents.get(event_id)):
            suffix = _format_intent(entry, session_anchor_timestamps)
        lines.append(
            f"- [id: {event_id}] {item.get('content', '')} ({age_str} old){suffix}"
        )
        if commit_overlap and event_id in commit_overlap:
            msgs = "; ".join(
                c.get("content", "")[:80] for c in commit_overlap[event_id][:3]
            )
            lines.append(f"  **MAYBE ADDRESSED** by: {msgs}")
    return "\n".join(lines)


def run(smm_dir: Path) -> str:
    """Scan events and produce triage output."""
    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return ""

    all_resolved = resolution.collect_all_resolved_ids(
        resolution.compute_resolutions(events)
    )
    session_anchor_ts = session_history.filter_session_anchor_timestamps(events)

    # Deliberately NOT passed to find_unresolved. An adopted or deferred item is
    # OPEN, and it has four other readers (story-concern triage, end-session
    # carry-forward) that would silently lose it if the shared finder started
    # filtering on intent — laundering it in two new places instead of one.
    # Intent is presentation here: it annotates, it does not remove.
    intents = intent.build_triage_intent_map(events)

    debts = triage.find_unresolved(events, event_schema.EVENT_TYPE_DEBT, all_resolved)
    concerns = triage.find_unresolved(
        events, event_schema.EVENT_TYPE_CONCERN, all_resolved
    )
    questions = triage.find_unresolved(
        events, event_schema.EVENT_TYPE_QUESTION, all_resolved
    )

    overlap: dict[str, list[dict]] = {}
    for c in concerns:
        if hits := commits.find_addressing_commits(c, events):
            overlap[c.get("id", "")] = hits

    sections = [
        format_triage_section("Open Debts", debts, session_anchor_ts, intents=intents),
        format_triage_section(
            "Open Concerns",
            concerns,
            session_anchor_ts,
            commit_overlap=overlap,
            intents=intents,
        ),
        format_triage_section(
            "Open Questions", questions, session_anchor_ts, intents=intents
        ),
    ]
    return "\n\n".join(s for s in sections if s)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan events for unresolved debts/concerns/questions."
    )
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    if output := run(args.smm_dir):
        print(output)


if __name__ == "__main__":
    main()
