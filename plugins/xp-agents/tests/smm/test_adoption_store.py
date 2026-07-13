#!/usr/bin/env python3
"""Tests for smm/adoption_store.py — the durable adoption ledger.

The ledger exists because the intent record lives only in the event log, and
compaction archives the log. A triage-adopt `status` event is archived by the
FIRST compaction that crosses it; an adopt `decision` survives 3 sessions; a
retrospective is capped at the last 2, taking its nested Try ids with it. Once
any of those goes, the adoption is forgotten and the work is re-offered forever.

So the ledger is a SIDECAR, not a new event type. `events.jsonl` is append-only:
one permanent record per adoption is exactly the log growth this story exists to
END (the same log where commits are already 60-75% of every live file). The
sidecar is keyed on `(target_id, lane)` and UPSERTS, so re-adopting the same
target 100 times writes ONE record — that is the AC, enforced by construction
rather than by a cap.

Shape and I/O contract are copied from `session_history.py` per SMM constraint
83297d6921d4: `{"version": int, "entries": [...]}`, atomic write, symlink
rejection, fail-loud on corrupt JSON, bounded growth. Bounded here means TWO
mechanisms, because a sidecar that only grows has just moved the leak:
`drop_resolved` (an entry lives only while its target is OPEN) with a hard
`max_entries` cap. The cap is not merely a backstop: an adopted Try is never
closed by its own adoption, so the retro lane's entries are bounded by the cap
rather than by `drop_resolved`.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import adoption_store
from conftest import _SMMTestCase, make_event
from event_schema import (
    DISPOSITION_ADOPTED,
    DISPOSITION_DEFERRED,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_STATUS,
)
from resolution import (
    closed_target_ids as _closed,
)
from resolution import (
    collect_all_resolved_ids,
    compute_resolutions,
)

TRY_ID = "aa11bb22cc33"
DEBT_ID = "dd44ee55ff66"

# The prune signal comes from its REAL producer, never a test-local recipe. The
# ledger's whole correctness rests on the reader and the pruner agreeing about
# what "closed" means; a test that hand-rolled the set could agree with neither.


def _intent(
    intent: str = DISPOSITION_ADOPTED,
    *,
    intent_by: str = "ev0000000001",
    intent_ts: str = "2026-01-01T00:00:00+00:00",
    defer_count: int = 0,
) -> dict:
    """One lane-map value, in the shape `intent.build_*_intent_map` returns —
    the ledger's only producer reads exactly this."""
    return {
        "intent": intent,
        "intent_by": intent_by,
        "intent_ts": intent_ts,
        "defer_count": defer_count,
    }


class TestLoadAdoption(_SMMTestCase):
    def test_load_missing_returns_empty_document(self):
        self.assertEqual(
            adoption_store.load_adoption(self.smm_dir),
            {"version": adoption_store.SCHEMA_VERSION, "entries": []},
        )

    def test_corrupt_json_fails_loud(self):
        """Never corrupt, always recoverable: a half-written ledger must raise,
        not silently read as 'nothing was ever adopted' — which would re-offer
        every adopted item, the exact amnesia the ledger prevents."""
        (self.smm_dir / adoption_store.ADOPTION_FILENAME).write_text(
            "{not json", encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            adoption_store.load_adoption(self.smm_dir)

    def test_schema_invalid_fails_loud(self):
        (self.smm_dir / adoption_store.ADOPTION_FILENAME).write_text(
            json.dumps({"version": 99, "entries": []}), encoding="utf-8"
        )
        with self.assertRaises(ValueError):
            adoption_store.load_adoption(self.smm_dir)

    def test_load_rejects_symlink(self):
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(adoption_store.empty_adoption()), encoding="utf-8")
        (self.smm_dir / adoption_store.ADOPTION_FILENAME).symlink_to(real)
        with self.assertRaises(OSError):
            adoption_store.load_adoption(self.smm_dir)

    def test_save_rejects_symlink(self):
        real = self.smm_dir / "real.json"
        real.write_text(json.dumps(adoption_store.empty_adoption()), encoding="utf-8")
        (self.smm_dir / adoption_store.ADOPTION_FILENAME).symlink_to(real)
        with self.assertRaises(OSError):
            adoption_store.save_adoption(self.smm_dir, adoption_store.empty_adoption())

    def test_save_rejects_invalid_document(self):
        """Validation happens at WRITE time, so a bad document never lands on
        disk to fail some later reader."""
        with self.assertRaises(ValueError):
            adoption_store.save_adoption(self.smm_dir, {"version": 1, "entries": {}})

    def test_round_trip(self):
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_RETRO,
            {TRY_ID: _intent()},
        )
        adoption_store.save_adoption(self.smm_dir, doc)
        self.assertEqual(adoption_store.load_adoption(self.smm_dir), doc)


class TestFoldIntents(_SMMTestCase):
    """`fold_intents` is the UPSERT — the whole reason this is a sidecar and not
    an event."""

    def test_fold_records_the_intent(self):
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_TRIAGE,
            {DEBT_ID: _intent(intent_by="ev0000000009")},
        )
        self.assertEqual(
            doc["entries"],
            [
                {
                    "target_id": DEBT_ID,
                    "lane": adoption_store.LANE_TRIAGE,
                    "intent": DISPOSITION_ADOPTED,
                    "intent_by": "ev0000000009",
                    "intent_ts": "2026-01-01T00:00:00+00:00",
                    "defer_count": 0,
                }
            ],
        )

    def test_re_adopting_the_same_target_does_not_duplicate(self):
        """AC3, at the unit level: N adoptions of one target = ONE record.

        Not 'N records then capped' — genuinely one, keyed by (target_id, lane).
        A cap would still let the ledger churn and would evict OTHER targets to
        make room for one loud one.
        """
        doc = adoption_store.empty_adoption()
        for i in range(5):
            doc = adoption_store.fold_intents(
                doc,
                adoption_store.LANE_RETRO,
                {TRY_ID: _intent(intent_by=f"ev000000000{i}", defer_count=i)},
            )
        self.assertEqual(len(doc["entries"]), 1)
        # Last write wins: the freshest intent is the true one.
        self.assertEqual(doc["entries"][0]["intent_by"], "ev0000000004")
        self.assertEqual(doc["entries"][0]["defer_count"], 4)

    def test_same_target_id_in_two_lanes_stays_two_entries(self):
        """The key is (target_id, lane), not target_id. The two lanes ask
        different questions about the same id and must not overwrite each other."""
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_RETRO,
            {DEBT_ID: _intent(intent=DISPOSITION_DEFERRED)},
        )
        doc = adoption_store.fold_intents(
            doc, adoption_store.LANE_TRIAGE, {DEBT_ID: _intent()}
        )
        self.assertEqual(len(doc["entries"]), 2)
        self.assertEqual(
            {(e["lane"], e["intent"]) for e in doc["entries"]},
            {
                (adoption_store.LANE_RETRO, DISPOSITION_DEFERRED),
                (adoption_store.LANE_TRIAGE, DISPOSITION_ADOPTED),
            },
        )

    def test_fold_rejects_unknown_lane(self):
        with self.assertRaises(ValueError):
            adoption_store.fold_intents(
                adoption_store.empty_adoption(), "not-a-lane", {TRY_ID: _intent()}
            )

    def test_updating_an_entry_keeps_its_position(self):
        """Upsert-in-place, so the cap's 'newest N' slice cannot be gamed by
        re-adopting an old target — and entry order stays first-seen order."""
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_RETRO,
            {TRY_ID: _intent(), DEBT_ID: _intent()},
        )
        doc = adoption_store.fold_intents(
            doc, adoption_store.LANE_RETRO, {TRY_ID: _intent(intent_by="fresh")}
        )
        self.assertEqual([e["target_id"] for e in doc["entries"]], [TRY_ID, DEBT_ID])


class TestDropResolved(_SMMTestCase):
    """Bounding mechanism 1, and the anti-resurrection guard. An entry lives
    only while its target is OPEN."""

    def test_resolved_target_is_dropped(self):
        debt = make_event(
            EVENT_TYPE_DEBT, content="a debt", ts="2026-01-01T00:00:00+00:00"
        )
        closer = make_event(
            EVENT_TYPE_STATUS,
            content="dropped it",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_TRIAGE,
            {debt["id"]: _intent()},
        )

        doc = adoption_store.drop_resolved(doc, _closed([debt, closer]))
        self.assertEqual(doc["entries"], [])

    def test_open_target_is_kept(self):
        debt = make_event(
            EVENT_TYPE_DEBT, content="a debt", ts="2026-01-01T00:00:00+00:00"
        )
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_TRIAGE,
            {debt["id"]: _intent()},
        )
        doc = adoption_store.drop_resolved(doc, _closed([debt]))
        self.assertEqual(len(doc["entries"]), 1)

    def test_a_closer_naming_an_ARCHIVED_target_still_prunes(self):
        """The resurrection trap, at the unit level.

        `compute_resolutions` resolves through the id INDEX, so it can only mark
        a target resolved while the target's own event is still in the log. The
        ids this ledger remembers are exactly the ones whose events are GONE — so
        an index-only prune signal is blind precisely where the ledger lives. The
        closer here names a target no event in the log can name back; the entry
        must still go, or it outlives the closer (a transient `status`, archived
        on the very next pass) and the item reads adopted forever.
        """
        closer = make_event(
            EVENT_TYPE_STATUS,
            content="dropped the compacted-away Try",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
            metadata={"resolves": [TRY_ID]},
        )
        # The Try's retrospective is NOT in this list — it was archived.
        self.assertNotIn(
            TRY_ID,
            collect_all_resolved_ids(compute_resolutions([closer])),
            "guard the guard: if the resolver CAN see this closure, the "
            "index-free path was never exercised",
        )
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_RETRO,
            {TRY_ID: _intent()},
        )

        doc = adoption_store.drop_resolved(doc, _closed([closer]))
        self.assertEqual(doc["entries"], [])


class TestCap(_SMMTestCase):
    """Bounding mechanism 2 — the backstop. drop_resolved is the real bound;
    this only catches a pathological log."""

    def test_cap_keeps_the_newest_entries(self):
        doc = adoption_store.empty_adoption()
        for i in range(5):
            doc = adoption_store.fold_intents(
                doc, adoption_store.LANE_RETRO, {f"target{i}": _intent()}
            )
        doc = adoption_store.cap(doc, 2)
        self.assertEqual(
            [e["target_id"] for e in doc["entries"]], ["target3", "target4"]
        )

    def test_cap_is_a_no_op_below_the_limit(self):
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_RETRO,
            {TRY_ID: _intent()},
        )
        self.assertEqual(adoption_store.cap(doc, 10)["entries"], doc["entries"])


class TestEntriesForLane(_SMMTestCase):
    """The reader's view: lane → {target_id: intent-entry}, the same shape
    `intent.build_*_intent_map` returns, so a reader can merge the two."""

    def test_selects_only_the_lane_asked_for(self):
        doc = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_RETRO,
            {TRY_ID: _intent(intent_by="retro-ev")},
        )
        doc = adoption_store.fold_intents(
            doc, adoption_store.LANE_TRIAGE, {DEBT_ID: _intent(intent_by="triage-ev")}
        )

        retro = adoption_store.entries_for_lane(doc, adoption_store.LANE_RETRO)
        self.assertEqual(list(retro), [TRY_ID])
        self.assertEqual(retro[TRY_ID]["intent_by"], "retro-ev")
        # The projection drops the key fields — a merged map is keyed by
        # target_id and its values must look exactly like the log-derived ones.
        self.assertNotIn("target_id", retro[TRY_ID])
        self.assertNotIn("lane", retro[TRY_ID])

        triage = adoption_store.entries_for_lane(doc, adoption_store.LANE_TRIAGE)
        self.assertEqual(list(triage), [DEBT_ID])

    def test_empty_lane_is_empty_map(self):
        self.assertEqual(
            adoption_store.entries_for_lane(
                adoption_store.empty_adoption(), adoption_store.LANE_RETRO
            ),
            {},
        )


class TestRecordIntents(_SMMTestCase):
    """The IO shell compaction calls: load → fold every lane → drop resolved →
    cap → save. ONE pass, so fold and prune can never disagree about what is
    closed (see the resurrection trap in compact.py)."""

    def test_folds_prunes_and_persists_in_one_call(self):
        debt = make_event(
            EVENT_TYPE_DEBT, content="a debt", ts="2026-01-01T00:00:00+00:00"
        )
        gone = make_event(
            EVENT_TYPE_DEBT, content="closed debt", ts="2026-01-01T00:00:00+00:00"
        )
        closer = make_event(
            EVENT_TYPE_STATUS,
            content="dropped",
            ts="2026-01-02T00:00:00+00:00",
            working_on=[],
            metadata={"resolves": [gone["id"]]},
        )
        adoption_store.record_intents(
            self.smm_dir,
            {
                adoption_store.LANE_TRIAGE: {
                    debt["id"]: _intent(),
                    gone["id"]: _intent(),
                },
                adoption_store.LANE_RETRO: {TRY_ID: _intent()},
            },
            _closed([debt, gone, closer]),
        )

        doc = adoption_store.load_adoption(self.smm_dir)
        self.assertEqual(
            {(e["target_id"], e["lane"]) for e in doc["entries"]},
            {
                (debt["id"], adoption_store.LANE_TRIAGE),
                (TRY_ID, adoption_store.LANE_RETRO),
            },
            "the resolved target must not be recorded, and the open ones must be",
        )

    def test_second_call_does_not_duplicate(self):
        for _ in range(3):
            adoption_store.record_intents(
                self.smm_dir,
                {adoption_store.LANE_RETRO: {TRY_ID: _intent()}},
                _closed([]),
            )
        doc = adoption_store.load_adoption(self.smm_dir)
        self.assertEqual(len(doc["entries"]), 1)


if __name__ == "__main__":
    unittest.main()
