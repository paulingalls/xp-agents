#!/usr/bin/env python3
"""Concurrency tests for the whole-file rewriters: compact, repair, migrate.

All three do read → decide → `replace_events_file(snapshot)`, and the read is
NOT held under the exclusive lock that the replace takes. An event appended in
that window was never seen by the caller, so it is absent from the snapshot —
and absent from the archive the caller built from that same snapshot. Writing
the snapshot verbatim therefore ANNIHILATES it: it reaches neither
events.jsonl nor backups/.

The rule these tests pin: an event the caller never saw was never a candidate
for removal. Deliberate removals (archived, invalid, malformed) must still
happen — the mirror-image failure is resurrecting what a caller meant to drop.

The adoption ledger has the same shape of bug one level up: `record_intents`
is a load → fold → save with no lock across it, so two concurrent compactions
can lose an adoption memory.

And the archive itself is the same bug one layer OUT: `compact` and `repair`
delete what they archive, so the file under backups/ is the ONLY copy. A name
stamped at one-second resolution cannot carry that weight — two runs in the
same second name the same file, and the second write silently overwrites the
first run's only copy.
"""

import fcntl
import json
import sys
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
import adoption_store
import archive
import compact
import materialize
import migrate
import repair
from conftest import _SMMTestCase, make_event
from event_schema import (
    EVENT_TYPE_CUSTOMER_INPUT,
    EVENT_TYPE_SESSION_END,
    EVENT_TYPE_STATUS,
)
from materialize import read_curation_watermark

# How long the writer UNDER TEST pauses mid-critical-section to let the racing
# writer in. Broken (no lock), the racer takes the flock at once and the wait
# ends early — the whole test runs in ~40ms. Fixed, the racer is blocked and the
# wait always burns its full budget, so this IS a real 0.5s in the green path;
# it is the price of proving the block. Keep it generous: a racer starved past
# the budget on a loaded box would make a BROKEN build look green.
_LOCK_WAIT = 0.5

# Both same-second tests pin the archive clock here: the bug IS the one-second
# name resolution, so the two runs must land in the same tick to exercise it.
_FIXED_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


class _RewriteRaceMixin(_SMMTestCase):
    """Seeding + assertions shared by the three rewriter races."""

    def _seed_session(self, count: int = 3, session_num: int = 1) -> list[dict]:
        ts = f"2026-03-{session_num:02d}T00:00:00+00:00"
        events = [
            make_event(
                EVENT_TYPE_CUSTOMER_INPUT,
                content=f"session {session_num} event {i}",
                ts=ts,
            )
            for i in range(count)
        ]
        events.append(
            make_event(
                EVENT_TYPE_SESSION_END,
                content=f"end session {session_num}",
                ts=ts,
                working_on=[],
            )
        )
        return events

    def _append_during_rewrite(self, module, event: dict):
        """Land *event* in the window the bug lives in.

        The caller has already read (and released its shared lock); the
        exclusive lock has not been taken yet. Patching the module's
        `replace_events_file` reference puts the append at exactly that
        instant, deterministically — no threads, no sleeps.
        """
        real = _append_impl.replace_events_file

        def racing(*args, **kwargs):
            _append_impl.append_event(self.smm_dir, event)
            return real(*args, **kwargs)

        return mock.patch.object(module, "replace_events_file", racing)

    def _live_ids(self) -> set[str]:
        return {e["id"] for e in self._read_events()}

    def _archived_ids(self) -> set[str]:
        ids: set[str] = set()
        for archive_file in (self.smm_dir / "backups").glob("*.jsonl"):
            for line in archive_file.read_text().splitlines():
                if line.strip():
                    ids.add(json.loads(line)["id"])
        return ids

    def _assert_survived(self, event: dict) -> None:
        """The concurrent arrival is in the live log, and was not archived."""
        live, archived = self._live_ids(), self._archived_ids()
        self.assertIn(
            event["id"],
            live,
            "concurrent arrival is not in events.jsonl; "
            f"in backups/: {event['id'] in archived} "
            "(False on both = ANNIHILATED — no trace anywhere)",
        )
        self.assertNotIn(
            event["id"],
            archived,
            "concurrent arrival was archived — it was never a candidate for "
            "removal, so it belongs in the live log",
        )


class TestConcurrentAppendDuringCompaction(_RewriteRaceMixin):
    """compact.compact_after_curation must not eat an event that arrives mid-run."""

    def test_event_appended_mid_compaction_survives(self):
        old = self._seed_session(session_num=1)
        new = self._seed_session(session_num=2)
        self._write_events(old + new)
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeper")

        arrival = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="landed mid-compaction")
        with self._append_during_rewrite(compact, arrival):
            result = compact.compact_after_curation(self.smm_dir)

        self.assertGreater(result["archived"], 0, "test seeded nothing to archive")
        self._assert_survived(arrival)

    def test_deliberate_archive_still_happens(self):
        """The fix must not resurrect what compaction meant to archive."""
        old = self._seed_session(session_num=1)
        new = self._seed_session(session_num=2)
        self._write_events(old + new)
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeper")

        arrival = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="landed mid-compaction")
        with self._append_during_rewrite(compact, arrival):
            compact.compact_after_curation(self.smm_dir)

        live, archived = self._live_ids(), self._archived_ids()
        transient = old[0]["id"]
        self.assertIn(transient, archived)
        self.assertNotIn(transient, live)
        # Post-watermark events are untouched by the archive.
        for event in new:
            self.assertIn(event["id"], live)

    def test_preserved_arrival_is_still_undelivered_and_uncurated(self):
        """Surviving in the file is not enough — the watermarks must still point
        BELOW the preserved event, or it is swallowed instead of eaten.

        The merge makes the post-rewrite file LONGER than the caller's snapshot,
        so the two watermarks compaction resets can no longer be the file's
        length. Both must stay at the RETAINED count: the arrival sits above
        them, so the next prompt-nugget pass still delivers it and the next
        curation still treats it as uncurated. Set either to the real file
        length and every concurrent arrival is silently skipped — present on
        disk, never seen by anyone. Nothing else in the suite pins this.
        """
        old = self._seed_session(session_num=1)
        new = self._seed_session(session_num=2)
        self._write_events(old + new)
        materialize.write_curation_watermark(self.smm_dir, len(old), "xp-housekeeper")

        arrival = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="landed mid-compaction")
        with self._append_during_rewrite(compact, arrival):
            compact.compact_after_curation(self.smm_dir)

        surviving = self._read_events()
        self.assertLess(
            len(surviving),
            len(old + new) + 1,
            "test is not exercising the merge — nothing was archived",
        )

        nugget_wm = int((self.smm_dir / ".watermark-prompt-nugget").read_text().strip())
        undelivered = [e["id"] for e in surviving[nugget_wm:]]
        self.assertIn(
            arrival["id"],
            undelivered,
            "prompt-nugget watermark is at or past the preserved arrival — it "
            "will never be delivered",
        )

        curation_wm = read_curation_watermark(self.smm_dir)["event_count"]
        uncurated = [e["id"] for e in surviving[curation_wm:]]
        self.assertIn(
            arrival["id"],
            uncurated,
            "curation watermark counts the preserved arrival as already curated "
            "— the next compaction may archive an event nobody ever read",
        )


class TestConcurrentAppendDuringRepair(_RewriteRaceMixin):
    """repair.repair must preserve arrivals AND still drop what it counted."""

    def test_arrival_survives_while_bad_lines_still_dropped(self):
        good = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="keeper")
        # Parses as an object and has an id, but is missing required fields.
        invalid = {"id": "aaaaaaaaaaaa", "type": EVENT_TYPE_STATUS}
        self._write_raw_lines(
            [
                json.dumps(good),
                json.dumps(invalid),
                "{not json at all",
            ]
        )

        arrival = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="landed mid-repair")
        with self._append_during_rewrite(repair, arrival):
            result = repair.repair(self.smm_dir)

        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["malformed"], 1)

        live = self._live_ids()
        self.assertIn(arrival["id"], live, "concurrent arrival was eaten by repair")
        self.assertIn(good["id"], live)
        self.assertNotIn(
            invalid["id"],
            live,
            "repair resurrected the invalid event it had just counted and dropped",
        )
        raw = self.events_file.read_text()
        self.assertNotIn("{not json at all", raw, "repair resurrected a malformed line")

    def test_duplicate_ids_still_deduped(self):
        event = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="twice")
        self._write_raw_lines([json.dumps(event), json.dumps(event)])

        arrival = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="landed mid-repair")
        with self._append_during_rewrite(repair, arrival):
            result = repair.repair(self.smm_dir)

        self.assertEqual(result["duplicates"], 1)
        ids = [e["id"] for e in self._read_events()]
        self.assertEqual(ids.count(event["id"]), 1)
        self.assertIn(arrival["id"], ids)


class TestConcurrentAppendDuringMigration(_RewriteRaceMixin):
    """migrate.migrate_file must not eat an arrival, and must still migrate."""

    def test_arrival_survives_migration(self):
        stale = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="v1 event")
        stale["schema_version"] = 1
        stale["ts"] = "2026-03-01T00:00:00"  # no timezone — v1→v2 normalizes it
        self._write_events([stale])

        arrival = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="landed mid-migration")
        with self._append_during_rewrite(migrate, arrival):
            result = migrate.migrate_file(self.smm_dir)

        self.assertEqual(result["migrated"], 1)
        by_id = {e["id"]: e for e in self._read_events()}
        self.assertIn(arrival["id"], by_id, "concurrent arrival was eaten by migrate")
        self.assertEqual(by_id[stale["id"]]["schema_version"], 2)
        self.assertEqual(by_id[stale["id"]]["ts"], "2026-03-01T00:00:00+00:00")


class TestConcurrentAdoptionRecord(_SMMTestCase):
    """`record_intents` is a read-modify-write; without a lock it loses updates."""

    def _entry_ids(self) -> set[str]:
        data = adoption_store.load_adoption(self.smm_dir)
        return {e["target_id"] for e in data["entries"]}

    def _competing_writer(self, target_id: str, done: threading.Event):
        """A second compaction's record_intents, written by hand.

        It cannot call `record_intents` itself: that takes the lock via
        `flock_with_timeout`, which arms SIGALRM, and signals only work on the
        main thread. So it takes the same flock raw and does the same
        load → fold → save — which is exactly what a second PROCESS does.
        """
        real_load = adoption_store.load_adoption

        def run() -> None:
            fd = open(self.smm_dir / adoption_store.ADOPTION_LOCK_NAME, "a")  # noqa: SIM115
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                data = real_load(self.smm_dir)
                data = adoption_store.fold_intents(
                    data,
                    adoption_store.LANE_RETRO,
                    {
                        target_id: {
                            "intent": "adopted",
                            "intent_by": "bbbbbbbbbbbb",
                            "intent_ts": "2026-03-02T00:00:00+00:00",
                            "defer_count": 0,
                        }
                    },
                )
                adoption_store.save_adoption(self.smm_dir, data)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                fd.close()
                done.set()

        return threading.Thread(target=run)

    def test_concurrent_record_does_not_lose_an_adoption(self):
        """The classic lost update: A loads, B writes, A saves over B."""
        done = threading.Event()
        writer = self._competing_writer("bbbbbbbbbbbb", done)
        real_load = adoption_store.load_adoption

        def load_then_let_b_run(smm_dir):
            data = real_load(smm_dir)
            # B races here: between A's load and A's save. Under the lock B is
            # blocked and the wait simply times out.
            writer.start()
            done.wait(timeout=_LOCK_WAIT)
            return data

        with mock.patch.object(adoption_store, "load_adoption", load_then_let_b_run):
            adoption_store.record_intents(
                self.smm_dir,
                {
                    adoption_store.LANE_RETRO: {
                        "aaaaaaaaaaaa": {
                            "intent": "adopted",
                            "intent_by": "cccccccccccc",
                            "intent_ts": "2026-03-01T00:00:00+00:00",
                            "defer_count": 0,
                        }
                    }
                },
                set(),
            )

        writer.join(timeout=5.0)
        self.assertFalse(writer.is_alive(), "competing writer never finished")

        ids = self._entry_ids()
        self.assertIn("aaaaaaaaaaaa", ids)
        self.assertIn(
            "bbbbbbbbbbbb",
            ids,
            "lost update: the concurrent adoption was overwritten by a stale "
            "snapshot — the target reverts to amnesia",
        )

    def test_fold_never_regresses_defer_count(self):
        """The ledger read in `compact` sits OUTSIDE the lock, so an intent map
        can carry a stale `defer_count`. Folding must take the floor, never
        walk it back — the count is memory too."""
        data = adoption_store.fold_intents(
            adoption_store.empty_adoption(),
            adoption_store.LANE_RETRO,
            {
                "aaaaaaaaaaaa": {
                    "intent": "deferred",
                    "intent_by": "cccccccccccc",
                    "intent_ts": "2026-03-02T00:00:00+00:00",
                    "defer_count": 3,
                }
            },
        )
        stale = adoption_store.fold_intents(
            data,
            adoption_store.LANE_RETRO,
            {
                "aaaaaaaaaaaa": {
                    "intent": "deferred",
                    "intent_by": "dddddddddddd",
                    "intent_ts": "2026-03-03T00:00:00+00:00",
                    "defer_count": 1,
                }
            },
        )
        entry = stale["entries"][0]
        self.assertEqual(entry["defer_count"], 3)
        self.assertEqual(entry["intent_by"], "dddddddddddd", "fresher intent wins")


class TestArchiveNeverClobbers(_RewriteRaceMixin):
    """The archive is the ONLY copy of what the rewriter deleted.

    `compact` archives events and then removes them from events.jsonl;
    `repair` backs up the raw log and then drops the bad lines from it. In both
    cases backups/ holds the last copy, so a second run that reuses the name and
    overwrites it annihilates the first run's events exactly as surely as the
    snapshot bug did — gone from the log, gone from backups/, no trace.

    One-second timestamp resolution is the whole gap: every teammate compacts at
    SessionEnd, so same-second runs are ordinary in team mode.
    """

    def _frozen_second(self):
        """Pin the archive clock so both runs compute the same name.

        Patched on `archive`, which is where the timestamp is now stamped —
        both rewriters route their only-copy writes through it.
        """
        return mock.patch.object(
            archive, "datetime", mock.Mock(now=mock.Mock(return_value=_FIXED_NOW))
        )

    def test_second_compaction_in_same_second_keeps_first_archive(self):
        events = self._seed_session(count=5, session_num=1)
        self._write_events(events)

        # Run 1: archive the first slice, which compaction then deletes.
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeper")
        with self._frozen_second():
            first = compact.compact_after_curation(self.smm_dir)
        self.assertGreater(first["archived"], 0, "run 1 archived nothing")
        archived_by_run1 = self._archived_ids()

        # Run 2, SAME UTC second, archiving a DIFFERENT slice.
        materialize.write_curation_watermark(self.smm_dir, 3, "xp-housekeeper")
        with self._frozen_second():
            second = compact.compact_after_curation(self.smm_dir)
        self.assertGreater(second["archived"], 0, "run 2 archived nothing")

        live, archived = self._live_ids(), self._archived_ids()
        annihilated = (archived_by_run1 - archived) - live
        self.assertEqual(
            annihilated,
            set(),
            "run 2's archive clobbered run 1's — these events are in no archive "
            "and no longer in events.jsonl: ANNIHILATED",
        )

    def test_second_repair_in_same_second_keeps_first_backup(self):
        good = make_event(EVENT_TYPE_CUSTOMER_INPUT, content="keeper")
        bad_one = {"id": "aaaaaaaaaaaa", "type": EVENT_TYPE_STATUS}
        self._write_raw_lines([json.dumps(good), json.dumps(bad_one)])

        with self._frozen_second():
            repair.repair(self.smm_dir)
            # A second bad line arrives; repair runs again in the same second.
            bad_two = {"id": "bbbbbbbbbbbb", "type": EVENT_TYPE_STATUS}
            with self.events_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(bad_two) + "\n")
            repair.repair(self.smm_dir)

        backed_up = "".join(
            f.read_text() for f in (self.smm_dir / "backups").glob("*.jsonl")
        )
        self.assertIn(
            bad_one["id"],
            backed_up,
            "the second repair's backup clobbered the first's — the only copy of "
            "the line repair deleted is gone",
        )


if __name__ == "__main__":
    unittest.main()
