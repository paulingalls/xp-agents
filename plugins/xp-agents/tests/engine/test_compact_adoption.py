#!/usr/bin/env python3
"""Compaction folds adoption memory into the ledger before it destroys it.

Split from test_compact.py (which was at 488/500 before this suite) alongside
its siblings test_compact_curation.py / test_compact_curation_sprint.py — one
file per compaction concern.

**Every test here runs a REAL compaction and asserts the adopting event is
GENUINELY GONE from events.jsonl before asserting the intent survives.** That
order is the whole point. A test that leaves the event on disk would pass
without compaction ever having archived anything, proving nothing at all — it
would be green today and green after a regression that deletes the ledger.

The bug being pinned, observed live: the retro re-proposed debts whose originals
had been compacted away, and escalated one to HIGH after "7 sessions unresolved"
— when nothing could ever have resolved it, because the event no longer existed.
"""

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import adoption_store
import compact
import intent
import materialize
from conftest import (
    _SMMTestCase,
    adopt_try_event,
    defer_try_event,
    drop_try_event,
    make_event,
    make_retrospective_with_try,
    triage_event,
)
from event_schema import (
    DISPOSITION_ADOPTED,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_SESSION_STARTED,
    EVENT_TYPE_STATUS,
)
from resolution import collect_all_resolved_ids, compute_resolutions

TRY_ID = "aa11bb22cc33"


class _LedgerCompactionTestCase(_SMMTestCase):
    """Machinery for driving a compaction that really does archive the intent."""

    def _anchors(self, count: int = 4) -> list[dict]:
        """Session boundary anchors, dated past the writer's clock.

        An adopt `decision` is retained for _DECISION_MAX_AGE (3) sessions —
        counted as anchors NEWER than the decision's own `ts`. The adopt fixtures
        go through the real writer, which stamps `ts` with the wall clock, so
        anchors dated in the fixture's own past would age the decision by ZERO
        sessions and it would never be archived. The far-future date is what makes
        this suite exercise compaction at all.
        """
        return [
            make_event(
                EVENT_TYPE_SESSION_STARTED,
                content=f"start {i}",
                ts=f"2099-01-{i + 1:02d}T00:00:00+00:00",
            )
            for i in range(count)
        ]

    def _compact(self, pre_watermark: list[dict]) -> list[dict]:
        """Write *pre_watermark* + one uncurated trailing event, compact, and
        return the events that SURVIVED. The trailing event keeps the watermark
        honest: compaction only archives what has been curated."""
        trailing = make_event(
            EVENT_TYPE_STATUS, content="uncurated", ts="2026-06-01T00:00:00+00:00"
        )
        self._write_events([*pre_watermark, trailing])
        materialize.write_curation_watermark(
            self.smm_dir, len(pre_watermark), "xp-housekeeper"
        )
        compact.compact_after_curation(self.smm_dir)
        return self._read_events()

    def _assert_archived(self, live: list[dict], event: dict, what: str) -> None:
        """The falsifiability guard. Every surviving-intent assertion below is
        worthless unless the event carrying that intent is really gone."""
        self.assertNotIn(
            event["id"],
            {e["id"] for e in live},
            f"{what} is still in events.jsonl — compaction did not archive it, "
            f"so this test proves nothing about surviving compaction",
        )

    def _ledger(self) -> dict:
        return adoption_store.load_adoption(self.smm_dir)

    def _retro_map(self, live: list[dict]) -> dict:
        return intent.build_retro_intent_map(
            live, intent.retro_try_ids(live), ledger=self._ledger()
        )

    def _triage_map(self, live: list[dict]) -> dict:
        return intent.build_triage_intent_map(live, ledger=self._ledger())


class TestRetroLaneSurvivesCompaction(_LedgerCompactionTestCase):
    """AC1. A Try's id has no line of its own — it is nested inside the
    retrospective event, which is capped at the last 2. Once that event is
    archived, `retro_try_ids` returns ∅, every log-derived target is filtered
    away by the `∩ try_ids` scope, and the map falls silent."""

    def _adopted_try_then_two_newer_retros(self) -> tuple[list[dict], dict, dict]:
        retro = make_retrospective_with_try(TRY_ID)
        adopt = adopt_try_event(self.smm_dir, TRY_ID)
        # The retro cap is "last 2 across ALL events", so two NEWER retros are
        # what pushes the Try's retro out. Nothing else can archive it.
        newer = [make_retrospective_with_try(f"newer{i}") for i in range(2)]
        events = [retro, adopt, *newer, *self._anchors()]
        return events, retro, adopt

    def test_adopted_try_still_reads_adopted_after_its_events_are_archived(self):
        events, retro, adopt = self._adopted_try_then_two_newer_retros()

        live = self._compact(events)

        self._assert_archived(live, adopt, "the adopt decision")
        self._assert_archived(live, retro, "the retrospective carrying the Try")
        # The precise failure mode this closes: with the retro gone, the log can
        # no longer even NAME the Try, so a reader that goes through try_ids has
        # nothing left to intersect against.
        self.assertNotIn(
            TRY_ID,
            intent.retro_try_ids(live),
            "guard the guard: if the log can still name the Try, the ∩ try_ids "
            "path was never exercised and the ledger was never needed",
        )

        self.assertEqual(self._retro_map(live)[TRY_ID]["intent"], DISPOSITION_ADOPTED)

    def test_without_the_ledger_the_memory_is_gone(self):
        """The inverse pin: the same compacted log, read WITHOUT the ledger, is
        exactly the bug. If this ever passes, the test above has stopped proving
        the ledger is what saved the answer."""
        events, _, _ = self._adopted_try_then_two_newer_retros()
        live = self._compact(events)

        self.assertEqual(
            intent.build_retro_intent_map(live, intent.retro_try_ids(live)),
            {},
            "the log alone must have forgotten — otherwise the ledger is not "
            "what makes the test above pass",
        )


class TestTriageLaneSurvivesCompaction(_LedgerCompactionTestCase):
    """AC2. A triage disposition is a `status` event — TRANSIENT, so the FIRST
    compaction that crosses it archives it. It is the entire intent record."""

    def test_triage_adopted_debt_is_still_annotated_after_compaction(self):
        debt = make_event(
            EVENT_TYPE_DEBT, content="An adopted debt", ts="2026-01-01T00:00:00+00:00"
        )
        self._write_events([debt])
        adopt = triage_event(self.smm_dir, "triage-adopt", debt["id"])

        live = self._compact([debt, adopt, *self._anchors()])

        self._assert_archived(live, adopt, "the triage-adopt status event")
        # The debt itself is unresolved, so it is still offered — which is the
        # point: it comes back, and without the ledger it comes back UNANNOTATED
        # and gets re-adopted forever.
        self.assertIn(debt["id"], {e["id"] for e in live})

        self.assertEqual(
            self._triage_map(live)[debt["id"]]["intent"], DISPOSITION_ADOPTED
        )


class TestNoResurrection(_LedgerCompactionTestCase):
    """The trap the ledger creates if fold and prune are not one pass.

    `intent.py` suppresses any target named in a `metadata.resolves`. But once
    the CLOSING event is itself archived, the live log stops saying "closed"
    while the ledger still says "adopted" — and a finished item comes back as
    adopted, forever. Fold and prune therefore run in the SAME compaction pass,
    over the FULL pre-archive event list.
    """

    def test_adopted_then_dropped_does_not_come_back(self):
        retro = make_retrospective_with_try(TRY_ID)
        adopt = adopt_try_event(self.smm_dir, TRY_ID)
        drop = drop_try_event(self.smm_dir, TRY_ID)
        newer = [make_retrospective_with_try(f"newer{i}") for i in range(2)]

        live = self._compact([retro, adopt, drop, *newer, *self._anchors()])

        self._assert_archived(live, adopt, "the adopt decision")
        self._assert_archived(live, drop, "the CLOSING event")

        self.assertNotIn(
            TRY_ID,
            self._retro_map(live),
            "a dropped Try resurrected as adopted — fold and prune disagreed "
            "about what was closed",
        )
        self.assertEqual(
            self._ledger()["entries"],
            [],
            "the ledger kept an entry for a closed target; it will leak forever",
        )

    def test_a_try_dropped_after_its_retrospective_was_archived_does_not_resurrect(
        self,
    ):
        """The resurrection trap's live form, and the reason the prune signal is
        a UNION of two readings rather than just `compute_resolutions`.

        The ledger's whole population is targets whose events are GONE. But
        `compute_resolutions` resolves through the id index: a Try id only exists
        there while the retrospective NESTING it is still in the log. So once the
        retro is archived — the very condition the ledger exists to survive — a
        drop naming that Try resolves NOTHING. An index-only prune is therefore
        blind exactly where the ledger lives: the entry outlives the drop event
        (a transient `status`, archived on the next pass), and the Try reads as
        adopted forever, with no event left anywhere that could ever close it.
        """
        retro = make_retrospective_with_try(TRY_ID)
        adopt = adopt_try_event(self.smm_dir, TRY_ID)
        newer = [make_retrospective_with_try(f"newer{i}") for i in range(2)]

        # Pass 1: the feature doing its job — retro AND adopt are archived, and
        # the ledger is the only thing that still remembers the adoption.
        live = self._compact([retro, adopt, *newer, *self._anchors()])
        self._assert_archived(live, retro, "the retrospective carrying the Try")
        self._assert_archived(live, adopt, "the adopt decision")
        self.assertEqual(self._retro_map(live)[TRY_ID]["intent"], DISPOSITION_ADOPTED)

        # The customer changes their mind. Nothing left in the log can even NAME
        # the Try, so the resolver cannot see this closure at all.
        drop = drop_try_event(self.smm_dir, TRY_ID)
        after_drop = self._read_events()
        self.assertNotIn(
            TRY_ID,
            collect_all_resolved_ids(compute_resolutions(after_drop)),
            "guard the guard: if the resolver CAN still resolve the Try, the "
            "archived-target path was never exercised",
        )

        # Pass 2: the drop is transient, so this pass destroys it. It is the LAST
        # pass that can ever see the closure — the ledger must prune here or never.
        live = self._compact([*after_drop, make_event(EVENT_TYPE_STATUS, content="x")])
        self._assert_archived(live, drop, "the CLOSING event")

        self.assertNotIn(
            TRY_ID,
            self._retro_map(live),
            "a dropped Try resurrected as adopted, permanently — nothing will "
            "ever close it a second time",
        )
        self.assertEqual(self._ledger()["entries"], [])

    def test_a_target_closed_after_the_fold_is_pruned_on_the_next_pass(self):
        """The closure can arrive AFTER the adoption was already folded. The
        next compaction must drop the entry — this is what keeps the ledger
        bounded, not the cap."""
        debt = make_event(
            EVENT_TYPE_DEBT,
            content="Adopted then dropped",
            ts="2026-01-01T00:00:00+00:00",
        )
        self._write_events([debt])
        adopt = triage_event(self.smm_dir, "triage-adopt", debt["id"])

        round_one = self._compact([debt, adopt, *self._anchors()])
        self.assertIn(debt["id"], self._ledger()["entries"][0]["target_id"])

        closer = make_event(
            EVENT_TYPE_STATUS,
            content="Dropped it",
            ts="2026-05-01T00:00:00+00:00",
            working_on=[],
            metadata={"resolves": [debt["id"]]},
        )
        self._compact([*round_one, closer])

        self.assertEqual(self._ledger()["entries"], [])


class TestLedgerAddsNoPermanentEventRecord(_LedgerCompactionTestCase):
    """AC3. The durable channel adds at most ONE record per target, and
    `events.jsonl` does not grow per re-adoption.

    This is why the ledger is a sidecar rather than a `convention` event:
    compaction retains conventions UNCONDITIONALLY — no age, no cap, no
    resolution escape — so one convention per adoption would be one permanent
    line in an append-only file re-read by every hook invocation. That is the
    log growth this story exists to end, not a way to fix it.
    """

    def test_five_re_adoptions_leave_one_ledger_entry_and_no_permanent_events(self):
        retro = make_retrospective_with_try(TRY_ID)
        adopts = [adopt_try_event(self.smm_dir, TRY_ID) for _ in range(5)]
        newer = [make_retrospective_with_try(f"newer{i}") for i in range(2)]

        live = self._compact([retro, *adopts, *newer, *self._anchors()])

        entries = self._ledger()["entries"]
        self.assertEqual(
            [e["target_id"] for e in entries],
            [TRY_ID],
            "re-adopting a target must UPSERT, not append",
        )
        # The freshest adoption is the one remembered.
        self.assertEqual(entries[0]["intent_by"], adopts[-1]["id"])

        for adopt in adopts:
            self._assert_archived(live, adopt, "an adopt decision")


class TestLedgerIsWrittenOnlyWhenMemoryWouldBeLost(_LedgerCompactionTestCase):
    """The ledger is written by the thing that destroys the record, at the
    instant it would be destroyed. No archive, no loss, nothing to write."""

    def test_no_ledger_file_when_nothing_is_archived(self):
        self._write_events([make_event(EVENT_TYPE_STATUS, content="only event")])
        compact.compact_after_curation(self.smm_dir)

        self.assertFalse(
            (self.smm_dir / adoption_store.ADOPTION_FILENAME).exists(),
            "compaction archived nothing, so it had no memory to preserve",
        )


class TestDeferCountNeverFalls(_LedgerCompactionTestCase):
    """`defer_count` is a FLOOR on how long an item has been carried, and a floor
    that can drop is not a floor.

    The fold must therefore read the existing ledger back in and fold THROUGH it.
    `fold_intents` overwrites an entry's fields wholesale, so a fold that derived
    the map from the log alone would write back only the deferrals the log can
    still SEE — and deferrals are transient `status` events, so after a compaction
    it can see at most the newest one. The count would fall every time the item
    was carried again: exactly backwards.

    It stays a floor and not an exact total (SMM assumption 3d5566c03225): the two
    windows overlap by an unknowable amount, so `max` is taken rather than a sum,
    which would double-count every deferral present in both.
    """

    def test_a_third_deferral_does_not_shrink_the_remembered_count(self):
        retro = make_retrospective_with_try(TRY_ID)
        first_two = [defer_try_event(self.smm_dir, TRY_ID) for _ in range(2)]

        live = self._compact([retro, *first_two, *self._anchors()])
        for deferral in first_two:
            self._assert_archived(live, deferral, "a deferral")
        self.assertEqual(self._ledger()["entries"][0]["defer_count"], 2)

        # Carried AGAIN, in a later session. The log can now see exactly one
        # deferral; the other two exist only in the ledger.
        defer_try_event(self.smm_dir, TRY_ID)
        self._compact([*self._read_events(), *self._anchors()])

        self.assertGreaterEqual(
            self._ledger()["entries"][0]["defer_count"],
            2,
            "the ledger FORGOT deferrals it had already counted — a Try carried "
            "for three sessions now reads as freshly raised",
        )


class TestAnUnreadableLedgerCannotWedgeCompaction(_LedgerCompactionTestCase):
    """`load_adoption` fails LOUD, and compaction must not inherit that.

    Compaction is the only thing that bounds `events.jsonl`, and it reaches
    production two ways, both of which an unreadable ledger would break: `main()`
    (SessionEnd + PostCompact) catches only LockTimeoutError, so a ValueError
    escapes as a traceback; `smm_cli.complete_curation` suppresses OSError and
    ValueError, so it no-ops in silence. Either way compaction stops every
    session from then on, and the log grows forever — with no remedy but
    hand-deleting a file the user has never heard of. An unbounded log is a far
    worse failure than a forgotten adoption.
    """

    def _corrupt_case(self, body: str) -> list[dict]:
        (self.smm_dir / adoption_store.ADOPTION_FILENAME).write_text(
            body, encoding="utf-8"
        )
        debt = make_event(
            EVENT_TYPE_DEBT, content="An adopted debt", ts="2026-01-01T00:00:00+00:00"
        )
        self._write_events([debt])
        adopt = triage_event(self.smm_dir, "triage-adopt", debt["id"])
        with contextlib.redirect_stderr(io.StringIO()) as err:
            live = self._compact([debt, adopt, *self._anchors()])
        self.assertIn("adoption ledger", err.getvalue())
        self._assert_archived(live, adopt, "the triage-adopt status event")
        return live

    def test_corrupt_json_is_quarantined_and_the_log_still_compacts(self):
        live = self._corrupt_case("{not json")

        self.assertTrue((self.smm_dir / adoption_store.QUARANTINE_FILENAME).exists())
        self.assertEqual(len(self._ledger()["entries"]), 1, "rebuilt from the log")
        self.assertTrue(self._triage_map(live))

    def test_a_version_from_the_future_does_not_wedge_a_rolled_back_plugin(self):
        """The realistic path to an unreadable ledger: a newer plugin bumps
        SCHEMA_VERSION, the user rolls back, and the older code cannot read what
        the newer one wrote. Rolling back must not stop compaction forever."""
        self._corrupt_case(
            json.dumps({"version": adoption_store.SCHEMA_VERSION + 1, "entries": []})
        )

        self.assertTrue((self.smm_dir / adoption_store.QUARANTINE_FILENAME).exists())
        self.assertEqual(self._ledger()["version"], adoption_store.SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
