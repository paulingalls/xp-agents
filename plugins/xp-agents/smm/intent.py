#!/usr/bin/env python3
"""The INTENT link: which retro Tries and triage items were adopted or deferred.

Sits beside `resolution.py`, and the split between them is the point:

  * `resolution.py` owns the CLOSURE link — `metadata.resolves`, written only by
    a terminal disposition. It answers "is this finished with?"
  * this module owns the INTENT link — the target id in the top-level
    `references` field of an adopt/defer event. It answers "was this taken on or
    carried?" while the target stays OPEN.

Taking work on must not close the item that verifies the work landed, so the two
links live in different fields. The consequence for readers is this module's
whole reason to exist: a reader that asks `resolution.py` "was this adopted?"
gets `False` for an adopted item and re-proposes it forever.

Two entry points, deliberately NOT one global "id → disposition" map. A global
map recreates the bug it was built to fix, twice over:

 1. **A bare `references` link is not intent.** Events name ids for reasons that
    are the opposite of adoption — the auto-raised "stale question" concern names
    the question precisely to say it is being IGNORED. Measured against the live
    log, treating any reference as an adoption is 6:1 false positives. So an
    event is admitted only when `metadata.action` names THIS lane and
    `metadata.disposition` is non-terminal.

 2. **An adopting event's reference bag is not all adoptions.** A Try's
    `[refs: ...]` suffix carries the Try id PLUS the debt/concern ids the Try's
    prose is ABOUT. `build_retro_intent_map` therefore intersects the bag with
    the known Try ids; without that `∩`, a debt a Try merely cited would be
    marked adopted and quietly vanish from triage — the exact laundering this
    milestone exists to end.

Legacy events (already on disk, written before the lane tags existed) are read by
a per-lane rule, and one gap is honestly a gap:

  * retro adopt: a `decision` with a `retro-try-<slug>` topic and no
    `metadata.action`. 4 such events exist; without this they are re-proposed at
    the next kickoff.
  * retro defer: a `status` with `disposition=deferred` and no `metadata.action`,
    naming its Try in `references`. Recoverable, and recovered — the FORCE-CLOSE
    gate already counts this exact event.
  * triage adopt: a `status` with `disposition=adopted` and no `metadata.action`.
    Unambiguous because the retro lane's adoption is a `decision`, never a
    `status`.
  * **legacy `triage-defer` is UNRECOVERABLE.** It linked nothing at all — there
    is no id on the event to read — so the ~20 on disk cannot be detected by any
    rule. Their targets are simply re-offered, as they are today. This is stated
    rather than papered over: no rule here pretends to cover them.

That last fact is load-bearing twice over, not just an apology: because a legacy
triage-defer names NO id, an untagged deferred `status` that names a Try id can
only be a retro deferral. Both this module and the FORCE-CLOSE gate rest on it.
"""

from collections.abc import Callable
from pathlib import Path

import adoption_store
import event_schema
import resolution
from event_builder import REFERENCES_KEY
from event_metadata import (
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    STATUS_ACTION_RETRO_TRY_DISPOSITION,
    STATUS_ACTION_TRIAGE_DISPOSITION,
    event_action,
    intent_disposition,
)

# The topic prefix `/xp-work-selection adopt` slugs a retro-Try adoption with.
# Only used to read events written BEFORE the lane tag existed — a tagged event
# is identified by its tag, never by its topic.
_LEGACY_RETRO_TOPIC_PREFIX = "retro-try-"

# A lane's rule for an event carrying no lane tag: the disposition it records,
# or None. One per lane; see the module docstring for what each can recover.
LegacyRule = Callable[[dict], str | None]
# The ids one intent event names as its targets. The retro lane narrows the
# reference bag to Try ids; the triage lane's bag is already exactly one id.
TargetSelector = Callable[[dict], list[str]]


def retro_try_ids(events: list[dict]) -> set[str]:
    """Every retro Try id in *events*.

    Sourced from `resolution.index_event`, the single source of truth for what a
    link may name, so the scope this module intersects against cannot drift from
    the scope the resolver resolves against.
    """
    by_id: dict[str, dict] = {}
    for event in events:
        resolution.index_event(event, by_id)
    return {
        event_id
        for event_id, event in by_id.items()
        if event.get("type") == resolution.RETRO_TRY_TYPE
    }


def load_ledger(smm_dir: Path | None) -> dict | None:
    """The durable ledger for *smm_dir*, or None when there is nothing to read.

    Fail-QUIET, deliberately, and it is the one place in this story that is: the
    ledger ANNOTATES an item that the caller has already decided to show. A
    corrupt sidecar must not take down the retro or the triage preload with it —
    the worst case without it is the pre-story behaviour (the item is re-offered),
    which is bad but is not an outage. `adoption_store.load_adoption` still fails
    LOUD for its writer, where a silent empty read would destroy memory rather
    than merely forget it.
    """
    if smm_dir is None:
        return None
    try:
        return adoption_store.load_adoption(smm_dir)
    except (OSError, ValueError):
        return None


def build_retro_intent_map(
    events: list[dict], try_ids: set[str], *, ledger: dict | None = None
) -> dict[str, dict]:
    """Map retro-Try id → the intent recorded about it. See module docstring.

    Targets are `references ∩ try_ids`. The intersection is load-bearing: an
    adopt event's reference bag also holds the debt/concern ids the Try cites,
    and those are NOT being adopted.

    *ledger* closes the compaction gap this docstring used to merely confess.
    A Try id has no line of its own — it is nested inside the retrospective
    event — so once compaction archives that event `try_ids` goes empty, every
    log-derived target is filtered away, and the map falls silent: the Try reads
    as never-reviewed and is re-proposed forever. The ledger is therefore
    consulted DIRECTLY BY TARGET ID and never through `∩ try_ids`; putting it
    behind that intersection would filter it against the same empty set and fix
    nothing.

    Note the FORCE-CLOSE gate solves the "which id is the Try" question with a
    DIFFERENT rule (`_try_targets`: an id absent from the log's top-level ids is
    a Try). It fails toward "still fires", which is right for a gate. The two
    now agree for as long as the ledger remembers, rather than diverging the
    moment the retrospective is archived. If you change either rule, change it
    knowing the other exists.
    """
    return _build_intent_map(
        events,
        STATUS_ACTION_RETRO_TRY_DISPOSITION,
        _legacy_retro_disposition,
        lambda event: [
            ref for ref in event.get(REFERENCES_KEY) or [] if ref in try_ids
        ],
        _lane_entries(ledger, adoption_store.LANE_RETRO),
    )


def build_triage_intent_map(
    events: list[dict], *, ledger: dict | None = None
) -> dict[str, dict]:
    """Map triaged debt/concern/question id → the intent recorded about it.

    No intersection needed here: a triage disposition links exactly one id, the
    item being triaged.

    A triage disposition is a `status` event — TRANSIENT, so the FIRST compaction
    that crosses it archives it, and it is the entire intent record for this
    lane. *ledger* is what survives that. See `build_retro_intent_map`.
    """
    return _build_intent_map(
        events,
        STATUS_ACTION_TRIAGE_DISPOSITION,
        _legacy_triage_disposition,
        lambda event: list(event.get(REFERENCES_KEY) or []),
        _lane_entries(ledger, adoption_store.LANE_TRIAGE),
    )


def _lane_entries(ledger: dict | None, lane: str) -> dict[str, dict]:
    """One lane's remembered intents. Keyed by `(target_id, lane)` in the ledger,
    so one lane can never read the other's memory."""
    if not ledger:
        return {}
    return adoption_store.entries_for_lane(ledger, lane)


def _legacy_retro_disposition(event: dict) -> str | None:
    """The retro lane's rule for an event carrying no lane tag. Two shapes, one
    per disposition the lane could record before the tag existed:

      * ADOPT is a `decision` slugged with a `retro-try-<slug>` topic.
      * DEFER is a `status` with disposition=deferred. It is admitted on the
        disposition alone — no topic to check — which is safe only because
        `build_retro_intent_map` scopes its targets to `∩ try_ids`: the other
        untagged producer of a deferred status is the legacy triage-defer, and
        that linked NOTHING, so it can never name a Try id and can never arrive
        here. The FORCE-CLOSE gate counts this same event on this same argument
        (`_counts_as_retro_defer`); if one of the two ever stops, they have
        started reading one event two ways.

    A legacy defer that named its Try in `metadata.resolves` (the oldest shape,
    from when linking WAS closing) is deliberately not recovered as intent — it
    already CLOSED the Try, and terminal beats intent.
    """
    match event.get("type"):
        case event_schema.EVENT_TYPE_DECISION:
            topic = event.get("topic") or ""
            if topic.startswith(_LEGACY_RETRO_TOPIC_PREFIX):
                return DISPOSITION_ADOPTED
            return None
        case event_schema.EVENT_TYPE_STATUS:
            disposition = intent_disposition(event)
            return disposition if disposition == DISPOSITION_DEFERRED else None
        case _:
            return None


def _legacy_triage_disposition(event: dict) -> str | None:
    """The triage lane's rule for an event carrying no lane tag.

    Only `adopted` is recoverable. A legacy triage-defer linked nothing, so it
    carries no id to read — see the module docstring.
    """
    if event.get("type") != event_schema.EVENT_TYPE_STATUS:
        return None
    if intent_disposition(event) != DISPOSITION_ADOPTED:
        return None
    return DISPOSITION_ADOPTED


def _lane_disposition(event: dict, action: str, legacy: LegacyRule) -> str | None:
    """The intent *event* records in *action*'s lane, or None if it records none.

    The lane tag is checked FIRST and is decisive: a tagged event belongs to
    exactly the lane its tag names, so one lane's adoption can never be read as
    the other's. Only an event with no tag at all falls through to the lane's
    legacy rule — an event tagged for a different purpose entirely (a file write,
    a test run) is simply not an intent event and is rejected here.
    """
    tag = event_action(event)
    if tag is not None:
        return intent_disposition(event) if tag == action else None
    return legacy(event)


def _build_intent_map(
    events: list[dict],
    action: str,
    legacy: LegacyRule,
    targets: TargetSelector,
    remembered: dict[str, dict],
) -> dict[str, dict]:
    """The precedence walk both lanes share.

    Precedence: a terminal disposition (`metadata.resolves`) beats any intent;
    among intents the LIVE LOG beats the ledger; and within the log the LAST one
    wins. One walk, one copy — two hand-rolled copies is how the two lanes drift
    apart, which is the failure this module exists to fix.

    "Last" means last in FILE ORDER, NOT by `ts`. `ts` is stamped BEFORE the
    flock is taken (see `retro_metrics._collect_dropped_tries_recent`), so under
    concurrent writers two events can land in the file out of ts order. The log
    is append-only and flock-serialized, so file order IS causal order.

    *remembered* is the ledger's view of this lane, seeded FIRST so the log's
    walk overwrites it: the ledger is a snapshot taken at the last compaction,
    the log is now. Seeding it here rather than merging afterwards is what makes
    a closure suppress a REMEMBERED intent too — `closed` is computed from the
    live log and applied to both sources at once. Without that, a Try adopted and
    later dropped would come back as adopted the moment its adopt event was
    archived, and stay adopted forever.

    Each entry is `{intent, intent_by, intent_ts, defer_count}`. `defer_count`
    counts every deferral of that target, not just consecutive ones, so a Try
    deferred twice and then adopted still carries the honest count of how long it
    was carried.
    """
    intents: dict[str, dict] = {
        target_id: dict(entry) for target_id, entry in remembered.items()
    }
    # Held apart from `intents` because the log's walk REPLACES an entry
    # wholesale — a fresher deferral must overwrite the remembered intent, but
    # it must not take the remembered COUNT down with it.
    remembered_counts: dict[str, int] = {
        target_id: entry.get("defer_count") or 0
        for target_id, entry in remembered.items()
    }
    defer_counts: dict[str, int] = {}
    # Read off the WHOLE log up front, and applied at the end: a terminal
    # disposition wins over an intent regardless of which came first.
    #
    # NOT the same set the pruner uses. `compact._fold_adoption_ledger` prunes on
    # `resolution.closed_target_ids`, a strict SUPERSET of this one — it also
    # honours the weak `references` cascade, which this reader deliberately does
    # not. An earlier comment here claimed the two sets were shared "so the reader
    # and the pruner cannot disagree about what closed means". They can, and the
    # claim was false.
    #
    # It is not a live bug today: a retro Try carries no top-level `references`,
    # so it can never cascade-close, and the two sets coincide on every id this
    # map can hold. But the pruner is the stricter one, so a divergence can only
    # drop an entry the reader would still have shown — never resurrect a finished
    # item. If a future change gives Tries a `references` bag, revisit this: the
    # sets part company at exactly that point.
    closed: set[str] = resolution.claimed_resolved_ids(events)

    for event in events:
        disposition = _lane_disposition(event, action, legacy)
        if disposition is None:
            continue
        for target_id in targets(event):
            if disposition == DISPOSITION_DEFERRED:
                defer_counts[target_id] = defer_counts.get(target_id, 0) + 1
            # Plain assignment, so a later intent overwrites an earlier one —
            # and overwrites the ledger's remembered one, which is older by
            # construction.
            intents[target_id] = {
                "intent": disposition,
                "intent_by": event.get("id", ""),
                "intent_ts": event.get("ts", ""),
            }

    return {
        target_id: {
            **entry,
            # The larger of what the log can still SEE and what the ledger
            # REMEMBERS. The two count different windows and neither is complete
            # on its own: the ledger holds the count as of the last fold, the log
            # holds only the deferrals still on disk. Summing them double-counts
            # every deferral present in both windows; taking the log's alone makes
            # a Try carried for five sessions read as freshly raised the moment
            # compaction runs. The max never double-counts and never regresses —
            # an honest floor on how long the item has been carried.
            "defer_count": max(
                defer_counts.get(target_id, 0), remembered_counts.get(target_id, 0)
            ),
        }
        for target_id, entry in intents.items()
        if target_id not in closed
    }
