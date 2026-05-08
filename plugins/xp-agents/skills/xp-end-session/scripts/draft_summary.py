#!/usr/bin/env python3
"""Draft a session-summary candidate from events.jsonl.

Pure-stdlib helper for the /xp-end-session skill. Reads the SMM
events.jsonl from the prior session_end boundary forward and emits
JSON to stdout:

    {
      "summary": "<line-per-event narrative, trimmed to budget>",
      "open_questions": ["<event-id>", ...],
      "likely_addressed": ["<event-id>", ...],
      "uncommitted_count": <int>
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

# Fallback cap when no prior SESSION_END exists (first session, corruption
# recovery, or backfilled events). Without it, an N=10000 backfill would
# crowd the budget with stale events and discard recent signal.
_NO_BOUNDARY_TAIL_CAP = 200


def _build_summary(events: list[dict], budget: int) -> str:
    """Format selected events chronologically, capped at *budget* chars.

    On overflow, drop OLDEST lines so the narrative tail (most recent
    activity) is preserved for the LLM. Truncating the head loses what
    the user actually wants to remember about the just-finished session.
    """
    lines = [
        f"[{event.get('type', '')}] {event.get('content', '')}"
        for event in events
        if event.get("type") in _SUMMARY_TYPES
    ]
    summary = "\n".join(lines)
    if len(summary) <= budget:
        return summary
    # Reserve 4 chars for the prefix — tail slice may contain no newline
    # when a single event content exceeds budget (commits have no content cap).
    prefix = "...\n"
    tail = summary[-(budget - len(prefix)) :]
    nl = tail.find("\n")
    if nl != -1:
        tail = tail[nl + 1 :]
    return prefix + tail


def run(smm_dir: Path) -> dict:
    """Compute the draft payload for the SMM at *smm_dir*."""
    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return {
            "summary": "",
            "open_questions": [],
            "likely_addressed": [],
            "uncommitted_count": 0,
        }

    prior_end_ts = _common.prior_session_end_ts(events)
    if prior_end_ts:
        session_events = [e for e in events if e.get("ts", "") > prior_end_ts]
    else:
        session_events = events[-_NO_BOUNDARY_TAIL_CAP:]

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
        "uncommitted_count": _common.uncommitted_event_count(events),
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
