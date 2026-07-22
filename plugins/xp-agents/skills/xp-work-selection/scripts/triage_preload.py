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

import _common  # noqa: E402
import commits  # noqa: E402
import event_schema  # noqa: E402
import intent  # noqa: E402
import materialize  # noqa: E402
import resolution  # noqa: E402
import session_history  # noqa: E402
import triage  # noqa: E402

# Storage != injection. Events store up to the full CONTENT_BUDGETS cap (see
# event_schema.py) so the WHY survives; this kickoff block is read at every
# session start, so it stays a bounded excerpt with the event id attached --
# the full causal chain is one lookup away, never dropped.
#
# The bound is 400 -- deliberately the PREVIOUS content cap, not a smaller
# round number. That makes the contract exact: raising storage 400 -> 500 buys
# room for the WHY at a cost of ZERO extra injected bytes, and the triage block
# a lead reads at kickoff loses nothing it used to show. A tighter excerpt
# would hold cost flat too, but it would silently degrade the block BELOW its
# pre-existing quality -- and this block is how the lead decides what to adopt,
# so a mid-sentence cut through the WHY buys tokens by making that decision
# worse. If the block's total size ever needs to come down, the lever is the
# ITEM COUNT (aging/collapsing stale items), not lossy per-item truncation.
_EXCERPT_MAX_CHARS = 400

# The digest bound is NOT a smaller _EXCERPT_MAX_CHARS, and reading it as one is
# story-013's mistake wearing a new number. 400 is a bounded excerpt of the WHY,
# sized so the lead can TRIAGE THE ITEM FROM THE BLOCK. A digested item is one
# the lead has ALREADY triaged — they deferred it themselves — so its line is an
# INDEX ENTRY: enough to recognise the item, plus the id that retrieves the whole
# thing. Cutting the full items to 60 would cut mid-WHY through items nobody has
# judged yet; cutting an already-deferred item to 60 honours the lead's own
# decision. The two bounds answer different questions; do not converge them.
_DIGEST_EXCERPT_MAX_CHARS = 60


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

    The section is rendered in two parts: items the lead has not deferred at
    full length, then a DIGEST sub-block for the ones they have (`_digests`).
    The digest is a shorter FORM, not a filter — every open item still gets a
    line of its own carrying its id, its DEFERRED count and any addressing
    commits, and the sub-block header names how many items are down there. An
    item that vanished would read as fixed; an item that shrank reads as
    carried, which is what it is.
    """
    if not items:
        return ""
    # One pass, so both parts keep the caller's newest-first order.
    full: list[dict] = []
    digest: list[dict] = []
    for item in items:
        (digest if _digests(item, intents) else full).append(item)

    lines = [f"### {header}:"]
    for item in full:
        lines.append(_full_line(item, session_anchor_timestamps, intents))
        lines.extend(_maybe_addressed_lines(item, commit_overlap))
    if digest:
        # Per SECTION, not global: this function renders one section, so the
        # count a reader sees is that section's own. The command is spelled
        # RUNNABLE (the same form as every other shipped invocation), not
        # shortened to a bare `smm_cli.py`: the digest's entire honesty claim is
        # that the id retrieves the whole item, and a retrieval path the reader
        # cannot execute is not a retrieval path.
        plural = "s" if len(digest) != 1 else ""
        lines.append(
            f"#### Deferred earlier — {len(digest)} item{plural}, full text via "
            f"`python3 ${{CLAUDE_PLUGIN_ROOT}}/smm/smm_cli.py --smm-dir <SMM_DIR> "
            f"get-event <id>`:"
        )
        for item in digest:
            lines.append(_digest_line(item, session_anchor_timestamps, intents))
            lines.extend(_maybe_addressed_lines(item, commit_overlap))
    return "\n".join(lines)


def _digests(item: dict, intents: dict[str, dict] | None) -> bool:
    """Whether *item* earns the shorter form: the lead has DEFERRED it.

    Deferral is the signal because it is the lead's own recorded judgement about
    this item — not a proxy for one. (Age is not available as a signal here:
    `sessions_since_event` counts RETAINED session anchors and compaction
    archives them, so on a real log every open item ages to a handful of values
    and no threshold discriminates.)
    """
    entry = (intents or {}).get(item.get("id", ""))
    return bool(entry) and entry["intent"] == event_schema.DISPOSITION_DEFERRED


def _full_line(
    item: dict, session_anchor_timestamps: list[str], intents: dict[str, dict] | None
) -> str:
    age = event_schema.sessions_since_event(
        session_anchor_timestamps, item.get("ts", "")
    )
    age_str = f"{age} sessions" if age != 1 else "1 session"
    excerpt = _common.truncate(item.get("content", ""), _EXCERPT_MAX_CHARS)
    suffix = _intent_suffix(item, session_anchor_timestamps, intents)
    return f"- [id: {item.get('id', '')}] {excerpt} ({age_str} old){suffix}"


def _digest_line(
    item: dict, session_anchor_timestamps: list[str], intents: dict[str, dict] | None
) -> str:
    """One digested item. Keeps the id, a recognisable excerpt and the DEFERRED
    count — everything that says "this is still open, and you carried it".

    Age is the one field the digest drops: the deferral count already tells the
    lead how long they have been carrying the item, and it tells it more
    honestly than an anchor count that compaction resets.
    """
    excerpt = _common.truncate(item.get("content", ""), _DIGEST_EXCERPT_MAX_CHARS)
    suffix = _intent_suffix(item, session_anchor_timestamps, intents)
    return f"- [id: {item.get('id', '')}] {excerpt}{suffix}"


def _intent_suffix(
    item: dict, session_anchor_timestamps: list[str], intents: dict[str, dict] | None
) -> str:
    if intents and (entry := intents.get(item.get("id", ""))):
        return _format_intent(entry, session_anchor_timestamps)
    return ""


def _maybe_addressed_lines(
    item: dict, commit_overlap: dict[str, list[dict]] | None
) -> list[str]:
    """The addressing-commit annotation, emitted for FULL AND DIGESTED items
    alike — one renderer, so the two forms cannot drift apart.

    Dropping it from digest lines is not "one lookup away": `get-event <id>`
    returns the concern EVENT, and these commits are derived at render time by
    `commits.find_addressing_commits`. They are never stored on the event, so
    there is no retrieval path for them. Close-pipeline Step 5b walks exactly
    this annotation to judge "did a commit already fix this?", and most
    MAYBE-ADDRESSED concerns are deferred — dropping the list here would take
    the deciding evidence away from the reader that exists to act on it.
    """
    event_id = item.get("id", "")
    if not commit_overlap or event_id not in commit_overlap:
        return []
    msgs = "; ".join(c.get("content", "")[:80] for c in commit_overlap[event_id][:3])
    return [f"  **MAYBE ADDRESSED** by: {msgs}"]


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
    intents = intent.build_triage_intent_map(events, ledger=intent.load_ledger(smm_dir))

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
