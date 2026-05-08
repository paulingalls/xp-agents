#!/usr/bin/env python3
"""Draft a session-summary candidate from events.jsonl.

Pure-stdlib helper for the /xp-end-session skill. Reads the SMM
events.jsonl from the prior session_end boundary forward and emits
JSON to stdout:

    {
      "summary": "<line-per-event narrative, trimmed to budget>",
      "open_questions": ["<event-id>", ...],
      "likely_addressed": [
          {"id": "<concern_id>", "commits": ["<commit_id>", ...]},
          ...
      ],
      "uncommitted_count": <int>,
      "carry_forward": [{"note", "references", "recommendation"}, ...]
    }

`likely_addressed` carries only IDs — the agent fetches concern and
commit content from its conversation history (solo work) or via Read
on events.jsonl (teammate-authored commits). Keeping the preload
minimal is intentional: the agent's judgement is the contract, not a
pre-rendered string.
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

# Cap on the carry_forward `note` field. Keeps the persisted ring-buffer
# entries compact — the full content is still recoverable via `references`.
_CARRY_FORWARD_NOTE_CAP = 100


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


def _carry_entry(item: dict, recommendation: str) -> dict:
    return {
        "note": _common.truncate(item.get("content", ""), _CARRY_FORWARD_NOTE_CAP),
        "references": [item.get("id", "")],
        "recommendation": recommendation,
    }


def _build_carry_forward(
    open_questions: list[dict],
    open_concerns: list[dict],
    likely_addressed_ids: set[str],
) -> list[dict]:
    """Build carry_forward candidates from open questions + unresolved high concerns.

    Recommendations: open questions and most concerns get "triage" (next
    session should decide). High-severity concerns get "watch" — they're
    not necessarily actionable next session, but should remain visible
    until resolved or downgraded. Differentiation lets future kickoff
    UIs route the two classes differently without re-deriving severity.

    `likely_addressed_ids` filters out concerns whose files were touched by a
    later commit (see triage.find_overlapping_commits) — those are speculatively
    closed and shouldn't crowd next session's triage.
    """
    carry = [_carry_entry(q, "triage") for q in open_questions]
    for concern in open_concerns:
        if concern.get("severity") != "high":
            continue
        if concern.get("id", "") in likely_addressed_ids:
            continue
        carry.append(_carry_entry(concern, "watch"))
    return carry


def run(smm_dir: Path) -> dict:
    """Compute the draft payload for the SMM at *smm_dir*."""
    events, _ = materialize.parse_events(smm_dir)
    if not events:
        return {
            "summary": "",
            "open_questions": [],
            "likely_addressed": [],
            "uncommitted_count": 0,
            "carry_forward": [],
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

    likely_addressed = []
    for item in open_concerns + open_debts:
        overlapping = triage.find_overlapping_commits(item, events)
        if not overlapping:
            continue
        likely_addressed.append(
            {"id": item["id"], "commits": [c["id"] for c in overlapping]}
        )

    likely_addressed_ids = {item["id"] for item in likely_addressed}
    carry_forward = _build_carry_forward(open_qs, open_concerns, likely_addressed_ids)

    return {
        "summary": summary,
        "open_questions": [q.get("id", "") for q in open_qs],
        "likely_addressed": likely_addressed,
        "uncommitted_count": _common.uncommitted_event_count(events),
        "carry_forward": carry_forward,
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
