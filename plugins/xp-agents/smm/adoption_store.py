#!/usr/bin/env python3
"""The durable adoption ledger: one rolling record per adopted/deferred target.

`intent.py` reads the INTENT link — "was this taken on, or carried?" — out of the
event log. But the log is COMPACTED, and compaction erases exactly the events that
carry the answer:

  * a triage-adopt `status` event is TRANSIENT — the first compaction that crosses
    it archives it, and it is the entire intent record for that lane.
  * an adopt `decision` survives `_DECISION_MAX_AGE` sessions, then goes.
  * a `retrospective` is capped at the last 2, and Try ids have no line of their
    own — they are nested inside it. Once it is archived, `retro_try_ids` returns
    ∅ and the retro intent map falls silent.

The Try items themselves are re-offered from `retrospectives/*.json`, which is NOT
compacted. So the item comes back while the memory of adopting it does not: work is
re-proposed forever, and an item nothing could resolve gets escalated for going
"unresolved" for N sessions. Adopted work is not finished work, but it is also not
forgotten work.

**Why a sidecar and not a `convention` event.** A durable event would have to be a
convention (compaction retains those unconditionally — no age, no cap, no escape),
which means one PERMANENT `events.jsonl` line per adoption. `events.jsonl` is
append-only and re-read by every hook invocation; a per-adoption permanent record
is precisely the log growth this story exists to stop. A sidecar keyed on
`(target_id, lane)` UPSERTS instead: re-adopting a target 100 times writes ONE
record.

Shape and I/O follow the `session_history.py` template (SMM constraint
83297d6921d4) — `{"version": int, "entries": [...]}`, atomic write via tempfile +
rename, symlink rejection, fail-loud on corrupt JSON, bounded growth:

    {
      "version": 1,
      "entries": [
        {"target_id": str, "lane": "retro"|"triage",
         "intent": "adopted"|"deferred", "intent_by": <event id>,
         "intent_ts": ISO-8601, "defer_count": int},
        ...
      ]
    }

**Bounded means two mechanisms, not one.** A sidecar that only grows has merely
moved the leak. `drop_resolved` is the primary bound — an entry lives only while
its target is OPEN — and it carries the triage lane outright, because a debt or
concern does get resolved. It does NOT fully carry the retro lane: adopting a Try
records intent and deliberately does not close it, so an adopted Try stays open
until something drops it or a commit resolves it, and plenty never are. Those
entries accumulate slowly (a few per retrospective), and `cap` is what actually
bounds them. So the cap is a real, reachable limit here, not only a
pathological-log backstop — and when it evicts, the oldest entry silently reverts
to the pre-ledger amnesia. Both run on every write via `record_intents`.

Pure module, no CLI. Its only writer is `compact.py`: the memory needs to become
durable at exactly the instant it would otherwise be lost, so the thing that
destroys the record is the thing that preserves it. That also means the ledger
cannot drift from the writers of the events — it is derived from those events.
"""

import contextlib
import json
from pathlib import Path

from _append_impl import write_text_atomic

ADOPTION_FILENAME = "adoption.json"
# Where an unreadable ledger is parked. Compaction bounds the event log and must
# never be wedged by this cache — see `quarantine_adoption`.
QUARANTINE_FILENAME = "adoption.json.corrupt"
SCHEMA_VERSION = 1

# Sized well above the open-item count of any plausible project. Reachable on the
# retro lane over a long project life (adopted Tries are never closed by their own
# adoption); see the module docstring for why that is expected, not a bug.
DEFAULT_MAX_ENTRIES = 200

# One lane per intent map in `intent.py`. The key is (target_id, lane), never
# target_id alone: the two lanes ask different questions and a target can appear
# in both.
LANE_RETRO = "retro"
LANE_TRIAGE = "triage"
VALID_LANES = frozenset({LANE_RETRO, LANE_TRIAGE})

# The fields an entry carries beyond its key. Same names `intent.build_*_intent_map`
# returns, so `entries_for_lane` projects straight back into a lane map and a
# reader can merge the two without translating.
_INTENT_FIELDS = ("intent", "intent_by", "intent_ts", "defer_count")


def validate_adoption(data: object) -> list[str]:
    """Validate an adoption ledger document.

    Returns a list of error strings — empty list means valid. Mirrors
    ``session_history.validate_session_history``.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["adoption must be an object"]

    if data.get("version") != SCHEMA_VERSION:
        errors.append(
            f"adoption version must be {SCHEMA_VERSION}, got {data.get('version')!r}"
        )

    entries = data.get("entries")
    if not isinstance(entries, list):
        errors.append("adoption.entries must be an array")
        return errors

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entries[{idx}] must be an object")
            continue
        if not isinstance(entry.get("target_id"), str) or not entry.get("target_id"):
            errors.append(f"entries[{idx}].target_id must be a non-empty string")
        if entry.get("lane") not in VALID_LANES:
            errors.append(
                f"entries[{idx}].lane must be one of {sorted(VALID_LANES)}, "
                f"got {entry.get('lane')!r}"
            )
        if not isinstance(entry.get("intent"), str):
            errors.append(f"entries[{idx}].intent must be a string")
        if not isinstance(entry.get("defer_count"), int) or isinstance(
            entry.get("defer_count"), bool
        ):
            errors.append(f"entries[{idx}].defer_count must be an integer")

    return errors


def empty_adoption() -> dict:
    """Return a fresh, valid adoption ledger document."""
    return {"version": SCHEMA_VERSION, "entries": []}


def load_adoption(smm_dir: Path) -> dict:
    """Read adoption.json from disk.

    Returns ``empty_adoption()`` when the file does not exist (fresh install, or
    a log that has never been compacted).

    Raises:
        ValueError: the file exists but is malformed or schema-invalid. Fail
            loud — a ledger that silently reads as empty re-offers every adopted
            item, which is the amnesia this module exists to end.
        OSError: the path is a symlink.
    """
    path = smm_dir / ADOPTION_FILENAME
    if path.is_symlink():
        raise OSError(f"adoption path is a symlink: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return empty_adoption()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt adoption ledger at {path}: {exc}") from exc

    errors = validate_adoption(data)
    if errors:
        raise ValueError(
            f"Schema-invalid adoption ledger at {path}: {'; '.join(errors)}"
        )
    return data


def quarantine_adoption(smm_dir: Path) -> Path:
    """Move an unreadable ledger aside so the next load starts clean.

    MOVES, never deletes: the bad copy is the only evidence of how it got that
    way, and the ledger holds intent the log may no longer be able to rebuild.
    Returns the quarantine path (whether or not anything was there to move — a
    failure to move is left to surface on the caller's retry, which will hit the
    same unreadable file and raise).

    Exists because `load_adoption` fails LOUD and compaction must not: see
    `compact._fold_adoption_ledger`.
    """
    dest = smm_dir / QUARANTINE_FILENAME
    with contextlib.suppress(OSError):
        (smm_dir / ADOPTION_FILENAME).replace(dest)
    return dest


def save_adoption(smm_dir: Path, data: dict) -> None:
    """Validate and atomically write adoption.json.

    Raises:
        ValueError: the data fails schema validation. The file on disk is left
            untouched.
        OSError: the target path is a symlink.
    """
    path = smm_dir / ADOPTION_FILENAME
    if path.is_symlink():
        raise OSError(f"adoption path is a symlink: {path}")

    errors = validate_adoption(data)
    if errors:
        raise ValueError(f"adoption validation failed: {'; '.join(errors)}")

    write_text_atomic(path, json.dumps(data, indent=2))


def fold_intents(data: dict, lane: str, intents: dict[str, dict]) -> dict:
    """UPSERT one lane's intent map into *data*, returning a new document.

    *intents* is `{target_id: {intent, intent_by, intent_ts, defer_count}}` — the
    exact shape `intent.build_*_intent_map` returns, so the ledger records what
    the readers read and cannot drift from it.

    Keyed on `(target_id, lane)`. An existing entry is updated IN PLACE, so:
      * re-adopting a target adds no second record (AC3, by construction), and
      * the cap's "newest N" slice cannot be gamed by re-adopting an old target,
        which would evict someone else's entry to re-seat one that was already
        seated.
    Last write wins on the fields — the freshest intent is the true one.
    """
    if lane not in VALID_LANES:
        raise ValueError(
            f"unknown lane {lane!r}; expected one of {sorted(VALID_LANES)}"
        )

    entries = [dict(e) for e in data.get("entries", [])]
    by_key = {(e.get("target_id"), e.get("lane")): e for e in entries}

    for target_id, recorded in intents.items():
        fields = {field: recorded.get(field) for field in _INTENT_FIELDS}
        if existing := by_key.get((target_id, lane)):
            existing.update(fields)
            continue
        entry = {"target_id": target_id, "lane": lane, **fields}
        entries.append(entry)
        by_key[(target_id, lane)] = entry

    return {**data, "entries": entries}


def drop_resolved(data: dict, resolved_ids: set[str]) -> dict:
    """Drop entries whose target has been resolved, returning a new document.

    The primary bound on the ledger's size: an entry lives only as long as its
    target is OPEN, and the set of open items is inherently small.

    It is also the anti-resurrection guard, and *resolved_ids* has to be built
    with that in mind — see `compact._fold_adoption_ledger`, which owns the
    recipe. Two properties are load-bearing:

      * it must be computed over the FULL PRE-ARCHIVE event list, so a closing
        event archived in THIS very pass is still seen; and
      * it must include ids read straight off `metadata.resolves`
        (`resolution.claimed_resolved_ids`) and not only ids the resolver could
        INDEX (`collect_all_resolved_ids`). The ids this ledger remembers are
        exactly the ones whose own events are gone, so an index-based resolver
        is blind precisely here: a Try dropped after its retrospective was
        archived resolves nothing, and the entry would never be pruned.

    Get either wrong and a finished item comes back as adopted — forever, since
    nothing will ever close it a second time.
    """
    if not resolved_ids:
        return data
    return {
        **data,
        "entries": [
            e for e in data.get("entries", []) if e.get("target_id") not in resolved_ids
        ],
    }


def cap(data: dict, max_entries: int = DEFAULT_MAX_ENTRIES) -> dict:
    """Trim to the newest *max_entries* entries, returning a new document.

    "Newest" is by FIRST SIGHTING, not by freshest intent — `fold_intents`
    updates in place, so an entry keeps its original position. Eviction is
    therefore oldest-adopted-first, which is the right thing to lose.

    `drop_resolved` is the primary bound; this is what actually bounds the retro
    lane, whose adopted Tries are never closed by their own adoption. See the
    module docstring.
    """
    entries = data.get("entries", [])
    if len(entries) <= max_entries:
        return data
    return {**data, "entries": entries[-max_entries:]}


def entries_for_lane(data: dict, lane: str) -> dict[str, dict]:
    """Project the ledger back into one lane map: `{target_id: {intent, ...}}`.

    Same shape `intent.build_*_intent_map` returns — the key fields (`target_id`,
    `lane`) are dropped — so a reader merges the two maps by `dict` update with
    no translation step in between.
    """
    return {
        entry["target_id"]: {field: entry.get(field) for field in _INTENT_FIELDS}
        for entry in data.get("entries", [])
        if entry.get("lane") == lane
    }


def record_intents(
    smm_dir: Path,
    intents_by_lane: dict[str, dict[str, dict]],
    resolved_ids: set[str],
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict:
    """Fold every lane's intents in, drop resolved targets, cap, and persist.

    ONE load and ONE save, so fold and prune see the same world and cannot
    disagree about what is closed. Prune runs AFTER fold, so a target closed in
    the same pass that recorded its intent leaves no entry behind.

    See `drop_resolved` for what *resolved_ids* must contain. Returns the saved
    document.
    """
    data = load_adoption(smm_dir)
    for lane, intents in intents_by_lane.items():
        data = fold_intents(data, lane, intents)
    data = cap(drop_resolved(data, resolved_ids), max_entries)
    save_adoption(smm_dir, data)
    return data
