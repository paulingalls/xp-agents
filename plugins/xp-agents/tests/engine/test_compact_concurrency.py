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
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
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
        for archive in (self.smm_dir / "backups").glob("*.jsonl"):
            for line in archive.read_text().splitlines():
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


if __name__ == "__main__":
    unittest.main()
