#!/usr/bin/env python3
"""Scan events.jsonl for unresolved debts, concerns, and questions.

Outputs formatted triage sections for the xp-work-selection preload.
"""

import argparse
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))

import event_schema  # noqa: E402
import materialize  # noqa: E402
import resolution  # noqa: E402
import session_history  # noqa: E402
import triage  # noqa: E402


def format_triage_section(
    header: str,
    items: list[dict],
    session_anchor_timestamps: list[str],
    *,
    commit_overlap: dict[str, list[dict]] | None = None,
) -> str:
    """Format a triage section with aging info."""
    if not items:
        return ""
    lines = [f"### {header}:"]
    for item in items:
        event_id = item.get("id", "")
        age = event_schema.sessions_since_event(
            session_anchor_timestamps, item.get("ts", "")
        )
        age_str = f"{age} sessions" if age != 1 else "1 session"
        lines.append(f"- [id: {event_id}] {item.get('content', '')} ({age_str} old)")
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

    debts = triage.find_unresolved(events, event_schema.EVENT_TYPE_DEBT, all_resolved)
    concerns = triage.find_unresolved(
        events, event_schema.EVENT_TYPE_CONCERN, all_resolved
    )
    questions = triage.find_unresolved(
        events, event_schema.EVENT_TYPE_QUESTION, all_resolved
    )

    overlap: dict[str, list[dict]] = {}
    for c in concerns:
        if hits := triage.find_overlapping_commits(c, events):
            overlap[c.get("id", "")] = hits

    sections = [
        format_triage_section("Open Debts", debts, session_anchor_ts),
        format_triage_section(
            "Open Concerns", concerns, session_anchor_ts, commit_overlap=overlap
        ),
        format_triage_section("Open Questions", questions, session_anchor_ts),
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
