# `get-event` is blind to 96.8% of this project's history

**Status:** proposed. **Triaged:** 2026-08-05 against `main` @ `e3f293e3`, plugin v5.5.0.
**Source:** `2026-08-02-get-event-blind-to-archived-events.md` (triaged and deleted; this doc is the surviving record).

## Problem

`smm_cli.py get-event` resolves ids against `events.jsonl` only. Once `compact` moves an event to `backups/archive-*.jsonl`, the only by-id reader reports `Event not found` — a false "does not exist" for a record that is on disk and permanently retained.

**Reproduced at HEAD** against this repo's own SMM (`~/.xp-agents/data/8e1f07eb0759/smm`):

```
$ python3 plugins/xp-agents/smm/smm_cli.py --smm-dir <SMM> get-event 3ac3d21d1668
Error: Event not found: '3ac3d21d1668'
```

(id taken from an `archive-*.jsonl`). Scale:

| | count |
|---|---|
| live `events.jsonl` | 830 |
| `archive-*.jsonl` files | 216 |
| archived events | 25,091 |
| **share of history unreachable by id** | **96.8%** |

`smm/archive.py:4-6` still states the archive is *"the ONLY copy of what was removed."* `scripts/pre_compact.py:61` rotates only `("events-*.jsonl", "SMM-*.json")`, so archives accumulate forever by design.

**Code path** (unchanged since the handoff — `git log --since=2026-08-01` on `smm_store.py`, `smm_cli.py`, `archive.py` returns nothing): `smm/smm_cli.py:255` `_cmd_get_event` → `smm/smm_store.py:188-202` `lookup_event` → `materialize.parse_events(smm_dir)`, live file only, raising at `:200`. No `--include-archived` flag (`smm_cli.py:372-373`); zero hits for `include_archived` anywhere; `smm_store.py` never mentions `archive`.

## Impact — with one correction to the handoff's own argument

The handoff listed three circulation paths for unreachable ids. Verified individually:

- **`xp-work-selection` preload — weaker than claimed.** `triage_preload.py:271` reads `materialize.parse_events(smm_dir)`, so every id it prints next to *"full text via … get-event <id>"* (`:163-167`) is live by construction. **Do not build the case on this bullet.**
- **Housekeeper curation — partly real.** `materialize.prepare_curation_data` also reads live events only, so `new_since_last_curation` ids resolve. But `agents/xp-housekeeper.md:19` instructs fetching truncated `customer_input` bodies via `get-event`, and `customer_input` is in `compact_retention._COMPACT_REFERENCE_TIED_TYPES` — it compacts away unpinned, so that instruction ages into a dead end.
- **Prose cross-references — the real impact, and it stands.** `AMENDS <id>`, `extends <id>`, `Resolves-Event: <id>` are the normal idiom in event bodies and concern text. They name whatever the id was when written, and that id ages into the archive. A "not found" reads as *this id is wrong*, inviting an agent to re-derive or silently drop a decision that is still on disk.

## Direction

On a live miss, fall back to the archives newest-first, and **mark provenance** (stderr note or an added key) so an archived hit is distinguishable from a live one. Count prefix matches across live ∪ archived so a prefix that is unique in `events.jsonl` but collides with an archived id cannot resolve silently.

**The one thing the handoff missed, and it is correctness-relevant.** `lookup_event` has **three** callers, two of which **mutate**:

- `smm_cli.py:255` `_cmd_get_event` — read-only, the intended beneficiary
- `smm_cli.py:196` `question --close-wont-fix` — appends a resolution event
- `smm_store.py:211` `promote_event` — writes a curated SMM item

A blanket fallback inside `lookup_event` would let `question --close-wont-fix` resolve a *compacted* question, appending a resolution for an event no longer in the working set. **The fallback must be opt-in at the call site** — `lookup_event(..., include_archived=True)` from `_cmd_get_event` only.

**Explicitly not in scope:** any change to `materialize.parse_events` (live-only is correct for renders, counts, and resolution cascades), to compaction, or to the no-rotation policy.

**Performance.** 25,091 events across 216 files is a full re-parse on the miss path. Acceptable — it runs only after the live lookup already failed, and newest-archive-first with an early return bounds the common case — but state it in the plan rather than discover it later.

**Fallback if the implicit fallback is rejected:** an explicit flag, but *only* if the not-found message names it:

```
Event not found: 'abc123' (searched events.jsonl; 25091 events exist in
backups/archive-*.jsonl -- retry with --include-archived)
```

That message alone closes most of the practical damage, converting a false "does not exist" into a true "not here, look there".

## Follow-on: the unlinkable-trailer producer, and an id-namespace collision

Two related items promoted from concerns filed at `low` by auto-producers.

**The producer is this reader's natural second consumer.** `scripts/commit_event.py:306-327` warns that a `Resolves-Event:` target is absent from the live log, honestly listing three possible causes. Verified on one instance: both ids resolved in `backups/archive-20260804T224300.jsonl` — the benign compacted case, so the warning carried nothing actionable. Once the archive reader lands, this call site should check the archives on the miss path and stay silent when the target is found there.

**But one cause it lists is not the real one** (concern `f266bdd59be3`). The id `eab677c3ed92` was searched across `events.jsonl` and all 216 archives and is not an event at all — it is a curated **Risk pillar-item id** (`backups/SMM-20260804-070747.json` → `risks[4]`). `smm_cli render` prints pillar ids as bare `[12-hex]`, indistinguishable from event ids, so commit `ba470dd7` picked one up for its trailer. All three causes named in the warning are therefore wrong for this instance.

Fix either by resolving trailers against pillar items too, or by making the two id namespaces distinguishable on sight. Whichever is chosen, the concern text needs rewriting rather than retaining — it currently teaches a reader three wrong things.

## Files

`smm/smm_store.py::lookup_event` (primary), `smm/smm_cli.py::_cmd_get_event` + parser at `:372`, plus a new archive-reading helper — **nothing in `smm/` currently reads `archive-*.jsonl` back**; `compact.py` and `archive.py` only write.

**Size:** medium (archive reader + opt-in plumbing + provenance signalling + cross-source ambiguity check + tests). **Dependencies:** none.
