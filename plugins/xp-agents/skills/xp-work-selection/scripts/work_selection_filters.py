#!/usr/bin/env python3
"""Pure filters over an event list for the adopt/defer/drop decision path.

No I/O, no flock — the caller does one locked read and feeds the list in, so
each filter is unit-testable without touching disk. Extracted from
work_selection_decide.py when it crossed the 500-line cap; the orchestration
(argparse, event construction, append) stays there and re-exports these names,
so callers and tests are unaffected by the move.

Names keep their leading underscore: they are internal to the work-selection
scripts, not a public surface — the trio of modules is one unit.
"""

import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "smm"))
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))

import _common  # noqa: E402
from event_builder import REFERENCES_KEY  # noqa: E402
from event_schema import (  # noqa: E402
    DISPOSITION_DEFERRED,
    EVENT_TYPE_STATUS,
    METADATA_KEY_RESOLVES,
    event_disposition,
    is_retro_lane,
)

# 3 prior deferrals = next plain defer is refused.
_FORCE_CLOSE_THRESHOLD = 3


def _counts_as_retro_defer(event: dict) -> bool:
    """Whether *event* is a deferral of a retro TRY, for FORCE-CLOSE purposes.

    Count it iff it is a deferring `status` in the retro lane — `is_retro_lane`
    (its tag names that lane, or it carries no tag at all).

    The lane check exists because a Try's ref bag holds the debt/concern ids the
    Try's prose CITES, and the triage lane now links its own deferrals in the
    same `references` field. Without it, deferring a *debt* would count as
    deferring every *Try* that merely mentioned that debt, inflating the Try's
    count toward a FORCE-CLOSE it never earned. (Live pair: Try 2b15e8490179's
    bag holds debt 9ec0731f5597, which already carries triage-defer 181cb8fa2316.)

    The untagged leg `is_retro_lane` admits is not speculative future-proofing:
    the tag is new and the gate is not, so every deferral written before the tag
    landed carries no `metadata.action`, and a bare `tag == retro` test would
    exclude all of them — zeroing those Tries' prior-defer counts and silently
    disarming the gate on precisely the long-carried Tries it exists to catch.
    Across this project's OWN history there are 134 untagged deferrals, 27 of
    which link a Try — live counts that leg is the only thing still collecting.

    Census that history, not the live log. Compaction moves old events out of
    events.jsonl into `backups/archive-*.jsonl`, and the gate only ever reads the
    live log — so a count taken there reports "no untagged deferrals" whenever a
    recent compaction has carried them off, and that is a statement about the
    compaction, not about the leg. Do not read such a zero as evidence the leg is
    dead and delete it.

    Counting untagged deferrals is SOUND because the legacy triage-defer linked
    NOTHING: an untagged deferral that carries a link is necessarily a retro
    deferral. Measured over that same history the invariant holds 134/134 — the
    107 linking nothing are all triage-defers, and all 27 that link name a Try.
    If a legacy triage-defer ever gains a link, this leg starts over-counting and
    must be revisited.

    The DISPOSITION set stays local. `is_retro_lane` answers only "which lane",
    because each reader's disposition question is its own: this gate counts
    deferrals, while the housekeeper's bucket also holds drops.
    """
    if event.get("type") != EVENT_TYPE_STATUS:
        return False
    if event_disposition(event) != DISPOSITION_DEFERRED:
        return False
    return is_retro_lane(event)


def _try_targets(events: list[dict], ref_ids: list[str]) -> set[str]:
    """The ids in *ref_ids* that name a TRY, not something the Try merely cites.

    A Try is a nested item inside a retrospective event: it has no line of its
    own in the log, so a Try id is NEVER a top-level event id. A debt/concern id
    the Try's prose cites always IS one. Filtering the bag against the log's
    top-level ids therefore separates the two without needing the retro that
    carries the Try to still be on disk.

    That last part is why this does not simply intersect against the retro Try
    ids: those live inside retrospective EVENTS, which compaction can archive,
    and a Try whose retro has aged out is exactly the long-carried Try the gate
    exists to catch. Subtracting known cited ids degrades the other way — an
    archived debt slips back into the bag and the gate over-counts as it does
    today — so the failure mode stays "gate still fires", never "gate silently
    disarmed".

    Falls back to the whole bag when nothing survives (a defer naming no Try at
    all), which preserves the pre-lane behaviour rather than disarming.

    NOT `resolution.resolvable_event_ids`, which looks like the helper for this
    and is the one thing that must not be used: it also lifts the nested try[]
    ids, so subtracting it would remove the TRY id — the only id that should
    survive — and zero every count, disarming the gate.
    """
    top_level_ids = {e["id"] for e in events if e.get("id")}
    return {r for r in ref_ids if r not in top_level_ids} or set(ref_ids)


def _count_prior_defers_filter(events: list[dict], ref_ids: list[str]) -> int:
    """Pure filter: count retro-Try deferrals (see `_counts_as_retro_defer`) of
    the Try named in ref_ids (see `_try_targets`). Each event contributes at most
    once.

    The two scopings are one rule applied to both halves of the bag leak. A Try's
    ref bag holds the Try id PLUS the debt/concern ids its prose cites, so
    matching on the raw bag counts any deferral that touches a CITED id — the
    lane check rejects a *debt's* own deferral, and `_try_targets` rejects
    another *TRY's* deferral arriving through a debt they both cite. Without the
    second, Try A is FORCE-CLOSE refused because Try B, which happens to cite the
    same debt, was deferred three times.

    BOTH link fields count. A deferral records intent, so it now names its Try
    in the top-level `references` field — but every deferral written before
    that routing existed names it in metadata.resolves. Reading only the
    current field would reset every Try's deferral count to zero and silently
    disarm the FORCE-CLOSE gate on exactly the Tries it exists to catch.
    """
    if not ref_ids:
        return 0
    targets = _try_targets(events, ref_ids)
    count = 0
    for e in events:
        if not _counts_as_retro_defer(e):
            continue
        meta = e.get("metadata") or {}
        links = set(meta.get(METADATA_KEY_RESOLVES) or []) | set(
            e.get(REFERENCES_KEY) or []
        )
        if targets.intersection(links):
            count += 1
    return count


def _convention_topic_exists_filter(events: list[dict], topic: str) -> bool:
    """Pure filter: True if `events` contains a convention event with `topic`.
    Used to make force-drop convention emission idempotent — re-drops of
    the same Try MUST NOT append a duplicate convention.
    """
    for e in events:
        if e.get("type") == _common.CONVENTION and e.get("topic") == topic:
            return True
    return False


def _cascade_ids_filter(events: list[dict], tokens: set[str]) -> set[str]:
    """Pure filter: ids of resolvable events (debt/concern/discovery) whose
    id appears in tokens. Caller unions this into metadata.resolves so a
    drop also closes the underlying signal.
    """
    return {
        e.get("id", "")
        for e in events
        if e.get("type") in _common.PROBE_RESOLVABLE_TYPES and e.get("id", "") in tokens
    }


def _force_close_message(ref_ids: list[str], prior: int) -> str:
    refs = ", ".join(r[:8] for r in ref_ids)
    return (
        f"FORCE-CLOSE: Try refs [{refs}] have {prior} prior deferrals "
        f"(threshold {_FORCE_CLOSE_THRESHOLD}). Plain defer refused. "
        "Re-run with --force-adopt <topic>, --force-drop, "
        "or --force-defer-with-date <YYYY-MM-DD>."
    )
