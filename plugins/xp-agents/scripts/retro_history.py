#!/usr/bin/env python3
"""Retrospective history gathering and Try-item annotation.

Reads the last N retrospective JSON files from ${SMM_DIR}/retrospectives/
and slims them for the retro analyst agent. Also cross-references the
most recent retro's Try items against this session's resolution map so
items that were already honored don't get re-flagged as "not honored".
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import intent
import marker_names
from event_schema import DISPOSITION_ADOPTED, EVENT_TYPE_DECISION

MAX_RETRO_HISTORY = 1
MAX_RETRO_FILE_SIZE = 1_048_576  # 1 MB

# 12+ char hex token — matches event IDs in Try text.
# Dict lookup downstream filters false positives (commit SHAs etc).
HEX_ID_RE = re.compile(r"\b[0-9a-f]{12,}\b")


def _slim_try_item(item) -> dict:
    """Slim a try item to {id?, content, event_refs}, handling legacy strings."""
    if isinstance(item, dict):
        slim: dict = {
            "content": item.get("content", ""),
            "event_refs": item.get("event_refs", []),
        }
        own_id = item.get("id")
        if own_id:
            slim["id"] = own_id
        return slim
    return {"content": item, "event_refs": []}


def gather_retro_history(smm_dir: Path, limit: int = MAX_RETRO_HISTORY) -> list[dict]:
    """Read the last N retrospective JSON files, slimmed for the retro agent.

    `keep` and `fix` become content-only strings. `try` becomes a list of
    `{content, event_refs}` dicts so the annotate step can cross-reference
    event IDs against the current session's resolutions. `analysis_notes`
    is preserved when present (carries cross-session trends). Legacy retros
    with list-of-strings `try` are migrated to the new shape on read.
    """
    retro_dir = smm_dir / marker_names.RETROSPECTIVES_DIR
    if not retro_dir.is_dir():
        return []

    files = sorted(retro_dir.glob("*.json"), reverse=True)
    result: list[dict] = []
    for f in files[:limit]:
        try:
            if f.stat().st_size > MAX_RETRO_FILE_SIZE:
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                slimmed: dict = {}
                if "timestamp" in data:
                    slimmed["timestamp"] = data["timestamp"]
                for field in ("keep", "fix"):
                    items = data.get(field, [])
                    slimmed[field] = [
                        item.get("content", item) if isinstance(item, dict) else item
                        for item in items
                    ]
                slimmed["try"] = [_slim_try_item(it) for it in data.get("try", [])]
                if "analysis_notes" in data:
                    slimmed["analysis_notes"] = data["analysis_notes"]
                result.append(slimmed)
        except (json.JSONDecodeError, OSError):
            continue
    return result


def _candidate_ids(item) -> list[str]:
    """The ids that may ANSWER for this Try.

    A Try that carries its OWN id is answered by that id ALONE. Ordering the ids
    by precedence and breaking on the first hit was not enough: precedence only
    decides which id is consulted FIRST, and the walk still FALLS THROUGH to the
    `event_refs` and prose tokens whenever the Try's own id has no answer — which
    is the common case, since most Tries are neither adopted nor closed. Those
    ids are the debt/concern ids the Try's prose is ABOUT (the same "a ref bag is
    not all targets" hazard `intent.build_retro_intent_map` intersects away with
    `∩ try_ids`), so a commit that closed a debt the Try merely CITES was
    reported as the TRY's closure: `resolved_this_session: True` for a Try nobody
    had done, which then drops out of re-proposal forever.

    There is nothing a fallback can add for an item that carries its own id, and
    everything for it to get wrong. So it gets none.

    A LEGACY Try — no id of its own — is a different case, and its fallback is
    NOT a leak. Such a Try has no other handle: `_preload_base.get_try_items`
    renders its `[refs: ...]` bag from `event_refs` alone, so `/xp-work-selection
    drop` closes it by resolving the CITED id, and its `event_refs` are the only
    thing that can say it was honoured. Filtering them out would not fix a false
    positive; it would delete the only closure signal the item has and re-propose
    a Try that was explicitly dropped. Order still decides which one answers, so
    it stays explicit: refs in order, then content tokens in match order,
    de-duplicated, first occurrence winning. (It was a `set`, which made the
    answer a function of PYTHONHASHSEED.)
    """
    if not isinstance(item, dict):
        return list(dict.fromkeys(HEX_ID_RE.findall(item or "")))
    if own_id := item.get("id"):
        return [own_id]
    ids: list[str] = [
        *item.get("event_refs", []),
        *HEX_ID_RE.findall(item.get("content", "")),
    ]
    return list(dict.fromkeys(ids))


def _try_status(item, resolutions_map: dict, intent_map: dict) -> dict:
    """The status of ONE Try: closure if it has one, else intent, else neither.

    Closure is consulted first for each candidate id, because terminal beats
    intent — a Try that was adopted and later dropped is dropped.

    Which ids may speak for the Try at all is `_candidate_ids`' business, and it
    is what keeps the CLOSURE channel from answering with the fate of a debt the
    Try merely cites. (The INTENT channel was already immune: its map is keyed by
    Try ids only.)

    The two answers stay in SEPARATE fields. `resolved_this_session` keeps its
    closure-only meaning; an adoption reports `intent` instead. Overloading
    `resolved_this_session` with "adopted" would hide the Try from work-selection
    AND tell the retro agent it was implemented — a fresh amnesia, symmetric to
    the one this milestone removes. Adopted is not done.
    """
    for token in _candidate_ids(item):
        if hit := resolutions_map.get(token):
            entry: dict = {
                "resolved_this_session": True,
                "resolver_id": hit["resolver_id"],
            }
            if disposition := hit.get("disposition"):
                entry["disposition"] = disposition
            elif hit.get("resolver_type") == EVENT_TYPE_DECISION:
                # Legacy read — the closure-channel twin of
                # `intent._legacy_retro_disposition`. Before adoption stopped
                # closing its target, adopting a Try wrote a `decision` carrying
                # metadata.resolves and no disposition. No writer emits that
                # shape now, but this reads the LOG, not the writers, and logs
                # written before the change still hold it — on this project's
                # own log, and on any install that upgrades mid-cycle. Such a
                # Try is CLOSED, so the intent map excludes it by design and
                # this is the only channel left that can speak for it. Silence
                # here would read as "landed by a commit" (the other resolver
                # that records no disposition) — a promise relabelled as
                # delivery, this milestone's amnesia pointing the other way.
                entry["disposition"] = DISPOSITION_ADOPTED
            return entry
        if recorded := intent_map.get(token):
            return {"resolved_this_session": False, **recorded}
    return {"resolved_this_session": False}


def annotate_try_status(
    previous_retros: list[dict],
    resolutions_map: dict,
    events: list[dict],
    smm_dir: Path | None = None,
) -> None:
    """Annotate Try items on previous_retros[0] with try_status.

    Attaches a parallel try_status list carrying two independent channels:
    CLOSURE (`resolved_this_session` + `disposition` + `resolver_id`) and INTENT
    (`intent` + `intent_by` + `intent_ts` + `defer_count`). See `_try_status`.

    Dropped Tries are NOT stripped — the agent prompt rule "disposition='dropped'
    — do not re-propose" needs to see them. Cross-session drop memory
    additionally surfaces via digest.dropped_tries_recent.

    Only the most recent retro gets annotated — older retros already went through
    a retro cycle, so their Try items are not candidates for re-proposal.

    *smm_dir* unlocks the durable side of the INTENT channel, and without it this
    annotation is exactly as amnesiac as it was. Try items are re-proposed from
    `retrospectives/*.json`, which is NEVER compacted, while the adoption that
    answers for them lives in the event log, which IS. So the item reliably comes
    back while the memory of adopting it does not. The ledger is what closes that
    asymmetry; None keeps the old (forgetful) behaviour for callers that have no
    SMM dir to read.
    """
    if not previous_retros:
        return
    latest = previous_retros[0]
    intent_map = intent.build_retro_intent_map(
        events, intent.retro_try_ids(events), ledger=intent.load_ledger(smm_dir)
    )
    latest["try_status"] = [
        _try_status(item, resolutions_map, intent_map) for item in latest.get("try", [])
    ]
