#!/usr/bin/env python3
"""Scan events.jsonl for unresolved debts, concerns, and questions.

Outputs formatted triage sections for work-selection preload. Replaces
the Risks-pillar question display with direct event scanning.
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import event_schema  # noqa: E402
import materialize  # noqa: E402
from resolution import compute_resolutions  # noqa: E402


def _collect_session_end_timestamps(events: list[dict]) -> list[str]:
    """Extract sorted session_end timestamps from events."""
    return sorted(
        e.get("ts", "")
        for e in events
        if e.get("type") == event_schema.EVENT_TYPE_SESSION_END
    )


def find_overlapping_commits(
    concern: dict,
    events: list[dict],
) -> list[dict]:
    """Find commit events whose files overlap the concern's files.

    Only considers commits after the concern's timestamp.
    """
    concern_files = set(concern.get("files") or [])
    if not concern_files:
        return []
    concern_ts = concern.get("ts", "")

    overlapping = []
    for e in events:
        if e.get("type") != event_schema.EVENT_TYPE_COMMIT:
            continue
        if e.get("ts", "") <= concern_ts:
            continue
        commit_files = set(e.get("files") or [])
        if concern_files & commit_files:
            overlapping.append(e)
    return overlapping


def find_unresolved(
    events: list[dict],
    event_type: str,
    resolved_ids: set[str],
) -> list[dict]:
    """Return unresolved events of a given type, newest first."""
    unresolved = [
        e
        for e in events
        if e.get("type") == event_type and e.get("id") not in resolved_ids
    ]
    return sorted(unresolved, key=lambda e: e.get("ts", ""), reverse=True)


def format_triage_section(
    header: str,
    items: list[dict],
    session_end_timestamps: list[str],
    *,
    commit_overlap: dict[str, list[dict]] | None = None,
) -> str:
    """Format a triage section with aging info."""
    if not items:
        return ""
    lines = [f"### {header}:"]
    for item in items:
        event_id = item.get("id", "")
        content = item.get("content", "")
        age = event_schema.sessions_since_event(
            session_end_timestamps, item.get("ts", "")
        )
        age_str = f"{age} sessions" if age != 1 else "1 session"
        lines.append(f"- [id: {event_id}] {content} ({age_str} old)")
        if commit_overlap and event_id in commit_overlap:
            msgs = "; ".join(
                c.get("content", "")[:80] for c in commit_overlap[event_id][:3]
            )
            lines.append(f"  **LIKELY ADDRESSED** by: {msgs}")
    return "\n".join(lines)


def run(smm_dir: Path) -> str:
    """Scan events and produce triage output."""
    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return ""

    resolutions = compute_resolutions(events)

    all_resolved: set[str] = set()
    for key in resolutions:
        if key.endswith("_ids"):
            all_resolved |= resolutions[key]

    session_end_ts = _collect_session_end_timestamps(events)

    concern_items = find_unresolved(
        events, event_schema.EVENT_TYPE_CONCERN, all_resolved
    )
    overlap: dict[str, list[dict]] = {}
    for concern in concern_items:
        hits = find_overlapping_commits(concern, events)
        if hits:
            overlap[concern.get("id", "")] = hits

    sections: list[str] = []
    for event_type, header in [
        (event_schema.EVENT_TYPE_DEBT, "Open Debts"),
        (event_schema.EVENT_TYPE_CONCERN, "Open Concerns"),
        (event_schema.EVENT_TYPE_QUESTION, "Open Questions"),
    ]:
        if event_type == event_schema.EVENT_TYPE_CONCERN:
            items = concern_items
            kw: dict = {"commit_overlap": overlap}
        else:
            items = find_unresolved(events, event_type, all_resolved)
            kw = {}
        section = format_triage_section(header, items, session_end_ts, **kw)
        if section:
            sections.append(section)

    return "\n\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scan events for unresolved debts/concerns/questions."
    )
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()

    output = run(args.smm_dir)
    if output:
        print(output)


if __name__ == "__main__":
    main()
