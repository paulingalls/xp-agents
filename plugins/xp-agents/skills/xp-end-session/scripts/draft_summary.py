#!/usr/bin/env python3
"""Draft a session-summary candidate from events.jsonl.

Pure-stdlib helper for the /xp-end-session skill. Reads the SMM
events.jsonl from the prior session_end boundary forward and emits
JSON to stdout:

    {
      "summary": "<line-per-event narrative, trimmed to budget>",
      "open_questions": ["<event-id>", ...],
      "likely_addressed": ["<event-id>", ...]
    }
"""

import argparse
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import event_schema  # noqa: E402
import materialize  # noqa: E402
import resolution  # noqa: E402
import triage  # noqa: E402

_SUMMARY_TYPES = frozenset(
    {
        event_schema.EVENT_TYPE_COMMIT,
        event_schema.EVENT_TYPE_DECISION,
        event_schema.EVENT_TYPE_CONCERN,
        event_schema.EVENT_TYPE_DEBT,
        event_schema.EVENT_TYPE_STATUS,
    }
)


def _build_summary(events: list[dict], budget: int) -> str:
    lines = [
        f"[{event.get('type', '')}] {event.get('content', '')}"
        for event in events
        if event.get("type") in _SUMMARY_TYPES
    ]
    return _common.truncate("\n".join(lines), budget)


def run(smm_dir: Path) -> dict:
    """Compute the draft payload for the SMM at *smm_dir*."""
    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return {"summary": "", "open_questions": [], "likely_addressed": []}

    prior_end_ts = _common.prior_session_end_ts(events)
    session_events = [e for e in events if e.get("ts", "") > prior_end_ts]

    budget = event_schema.get_required_budget(event_schema.EVENT_TYPE_SESSION_SUMMARY)
    summary = _build_summary(session_events, budget)

    # Resolution context uses the FULL event log so prior-session
    # resolutions are honored — concerns from prior sessions resolved
    # by this session's commits should not surface as "open" again.
    resolutions = resolution.compute_resolutions(events)
    answered_q_ids = resolutions.get("answered_question_ids", set())
    all_resolved = resolution.collect_all_resolved_ids(resolutions)

    open_qs = triage.find_unresolved(
        session_events, event_schema.EVENT_TYPE_QUESTION, answered_q_ids
    )
    open_concerns = triage.find_unresolved(
        session_events, event_schema.EVENT_TYPE_CONCERN, all_resolved
    )
    open_debts = triage.find_unresolved(
        session_events, event_schema.EVENT_TYPE_DEBT, all_resolved
    )

    likely_addressed = [
        item.get("id", "")
        for item in (open_concerns + open_debts)
        if triage.find_overlapping_commits(item, events)
    ]

    return {
        "summary": summary,
        "open_questions": [q.get("id", "") for q in open_qs],
        "likely_addressed": likely_addressed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draft a session_summary candidate from events.jsonl."
    )
    parser.add_argument("--smm-dir", type=Path, required=True, help="SMM directory")
    args = parser.parse_args()
    print(json.dumps(run(args.smm_dir)))


if __name__ == "__main__":
    main()
