#!/usr/bin/env python3
"""Draft a session-summary candidate from events.jsonl.

Pure-stdlib helper for the /xp-end-session skill. Reads the SMM
events.jsonl from the current session's session_started boundary forward
and emits JSON to stdout:

    {
      "summary": "<refined session_summary content if present;
                   else line-per-event narrative; trimmed to budget>",
      "open_questions": ["<event-id>", ...],
      "maybe_addressed": [
          {"id": "<concern_id>", "commits": ["<git_commit_hash>", ...]},
          ...
      ],
      "uncommitted_count": <int>,
      "carry_forward": [{"note", "references", "recommendation"}, ...]
    }

`maybe_addressed.commits` carries real git commit hashes (resolvable
via `git show`), not SMM commit-event ids. The agent fetches concern
content via Read on events.jsonl and commit content via `git show`.
Keeping the preload minimal is intentional: the agent's judgement is
the contract, not a pre-rendered string.
"""

import argparse
import json
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
import commits  # noqa: E402
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

# Fallback cap when no prior session_started anchor exists (first session,
# corruption recovery, or backfilled events). Without it, an N=10000 backfill
# would crowd the budget with stale events and discard recent signal.
_NO_BOUNDARY_TAIL_CAP = 200

# Cap on the carry_forward `note` field. Keeps the persisted ring-buffer
# entries compact — the full content is still recoverable via `references`.
_CARRY_FORWARD_NOTE_CAP = 100


def _build_summary(events: list[dict], budget: int) -> str:
    """Return the latest session_summary event content if present; else
    synthesize a chronological event-log narrative capped at *budget*.

    /xp-end-session Step 1 authors a refined past-tense session_summary;
    write_history must persist that, not the mechanical CANDIDATES dump.
    Fallback synthesis serves the CANDIDATES preload (no summary yet).
    On overflow of the synthesized path, drop OLDEST lines so the tail
    (most recent activity) is preserved for the LLM.
    """
    summaries = [
        e for e in events if e.get("type") == event_schema.EVENT_TYPE_SESSION_SUMMARY
    ]
    if summaries:
        return _common.truncate(summaries[-1].get("content", ""), budget)

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
    maybe_addressed_ids: set[str],
) -> list[dict]:
    """Build carry_forward candidates from open questions + unresolved high concerns.

    Recommendations: open questions and most concerns get "triage" (next
    session should decide). High-severity concerns get "watch" — they're
    not necessarily actionable next session, but should remain visible
    until resolved or downgraded. Differentiation lets future kickoff
    UIs route the two classes differently without re-deriving severity.

    `maybe_addressed_ids` filters out concerns a later commit likely
    addressed — file overlap OR an explicit id citation in the commit body
    (see commits.find_addressing_commits) — those are speculatively closed
    and shouldn't crowd next session's triage.
    """
    carry = [_carry_entry(q, "triage") for q in open_questions]
    for concern in open_concerns:
        if concern.get("severity") != "high":
            continue
        if concern.get("id", "") in maybe_addressed_ids:
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
            "maybe_addressed": [],
            "uncommitted_count": 0,
            "carry_forward": [],
        }

    session_start_ts = _common.current_session_start_ts(events)
    if session_start_ts:
        session_events = [e for e in events if e.get("ts", "") > session_start_ts]
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

    maybe_addressed = []
    for item in open_concerns + open_debts:
        overlapping = commits.find_addressing_commits(item, events)
        if not overlapping:
            continue
        # Emit git commit_hash (resolvable by `git show`), not the SMM
        # commit-event id. The post-commit hook records the real SHA in
        # metadata.commit_hash; agents downstream `git show` it to read
        # the commit body when judging concern resolution.
        # Filter (don't fall back) when commit_hash is missing — handing
        # back the SMM event id would re-introduce the very bug this
        # path fixes (event id is NOT a git ref).
        commit_hashes = [
            h
            for c in overlapping
            if (h := c.get("metadata", {}).get(event_schema.METADATA_KEY_COMMIT_HASH))
        ]
        if not commit_hashes:
            continue
        maybe_addressed.append({"id": item["id"], "commits": commit_hashes})

    maybe_addressed_ids = {item["id"] for item in maybe_addressed}
    carry_forward = _build_carry_forward(open_qs, open_concerns, maybe_addressed_ids)

    return {
        "summary": summary,
        "open_questions": [q.get("id", "") for q in open_qs],
        "maybe_addressed": maybe_addressed,
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
