#!/usr/bin/env python3
"""Tests for the repair and migration maintenance scripts.

Scale/parse-cost invariants live in test_scale_invariants.py.
Split from smm/test_engine.py.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import _append_impl
from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_STATUS

# ===========================================================================
# Repair (Milestone 8)
# ===========================================================================


class _CountingJson:
    """Stand-in for the json module that counts loads() calls.

    Everything else delegates to the real module — repair catches
    json.JSONDecodeError, so a plain MagicMock(wraps=json) breaks the except
    clause (a mock attribute is not an exception class) rather than counting.
    """

    def __init__(self):
        self.loads_calls = 0

    def loads(self, s, *args, **kwargs):
        self.loads_calls += 1
        return json.loads(s, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(json, name)


class TestRepair(_SMMTestCase):
    """Tests for smm/repair.py log recovery."""

    def test_repair_empty_log(self):
        import repair

        result = repair.repair(self.smm_dir)
        self.assertEqual(result["retained"], 0)
        self.assertEqual(result["malformed"], 0)

    def test_repair_valid_log_unchanged(self):
        import repair

        events = [make_event(), make_event(EVENT_TYPE_DECISION, topic="t")]
        self._write_events(events)
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["retained"], 2)
        self.assertEqual(result["malformed"], 0)
        self.assertEqual(result["invalid"], 0)

    def test_repair_skips_malformed_json(self):
        import repair

        good = make_event(content="good")
        self._write_raw_lines(
            [
                json.dumps(good),
                "not valid json {{{",
                '{"partial": true',
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["malformed"], 2)
        self.assertEqual(result["retained"], 1)

    def test_repair_skips_missing_required_fields(self):
        import repair

        good = make_event(content="good")
        bad_no_id = {
            "type": EVENT_TYPE_STATUS,
            "ts": "2026-01-01T00:00:00+00:00",
            "agent_id": "main",
            "content": "no id",
        }
        bad_no_type = {
            "id": "abc",
            "ts": "2026-01-01T00:00:00+00:00",
            "agent_id": "main",
            "content": "no type",
        }
        self._write_raw_lines(
            [
                json.dumps(good),
                json.dumps(bad_no_id),
                json.dumps(bad_no_type),
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["invalid"], 2)
        self.assertEqual(result["retained"], 1)

    def test_repair_deduplicates_by_id(self):
        import repair

        e = make_event(content="original")
        dupe = dict(e)
        dupe["content"] = "duplicate"
        self._write_events([e, dupe])
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["retained"], 1)
        # Retained should be the first occurrence
        retained = self._read_events()
        self.assertEqual(retained[0]["content"], "original")

    def test_repair_sorts_by_timestamp(self):
        import repair

        e1 = make_event(content="second", ts="2026-03-02T00:00:00+00:00")
        e2 = make_event(content="first", ts="2026-03-01T00:00:00+00:00")
        self._write_events([e1, e2])
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["reordered"], 1)
        retained = self._read_events()
        self.assertEqual(retained[0]["content"], "first")
        self.assertEqual(retained[1]["content"], "second")

    def test_repair_creates_backup(self):
        import repair

        self._write_events([make_event()])
        repair.repair(self.smm_dir)
        backups = self.smm_dir / "backups"
        self.assertTrue(backups.exists())
        pre_repairs = list(backups.glob("pre-repair-*.jsonl"))
        self.assertEqual(len(pre_repairs), 1)

    def test_repair_writes_report(self):
        import repair

        self._write_raw_lines([json.dumps(make_event()), "bad line"])
        repair.repair(self.smm_dir)
        report_file = self.smm_dir / ".repair-report.json"
        self.assertTrue(report_file.exists())
        report = json.loads(report_file.read_text())
        self.assertIn("malformed", report)
        self.assertIn("retained", report)

    def test_repair_dry_run_no_changes(self):
        import repair

        events = [make_event()]
        self._write_events(events)
        (self.smm_dir / "events.jsonl").read_text()
        self._write_raw_lines([json.dumps(events[0]), "bad"])

        result = repair.repair(self.smm_dir, dry_run=True)
        self.assertEqual(result["malformed"], 1)
        # File should be unchanged (still has the bad line)
        current = (self.smm_dir / "events.jsonl").read_text()
        self.assertIn("bad", current)

    def test_repair_atomic_replacement(self):
        import repair

        self._write_events([make_event()])
        repair.repair(self.smm_dir)
        # File should be valid JSONL
        for line in (self.smm_dir / "events.jsonl").read_text().splitlines():
            line = line.strip()
            if line:
                json.loads(line)

    def test_repair_non_object_lines_skipped(self):
        import repair

        self._write_raw_lines(
            [
                json.dumps(make_event()),
                '"just a string"',
                "42",
                json.dumps([1, 2, 3]),
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["invalid"], 3)
        self.assertEqual(result["retained"], 1)

    def test_repair_mixed_problems(self):
        """Combines malformed JSON, missing fields, duplicates, out-of-order."""
        import repair

        e1 = make_event(content="first", ts="2026-03-02T00:00:00+00:00")
        e2 = make_event(content="second", ts="2026-03-01T00:00:00+00:00")
        dupe = dict(e1)
        self._write_raw_lines(
            [
                json.dumps(e1),
                "bad json",
                json.dumps({"not": "valid event"}),
                json.dumps(e2),
                json.dumps(dupe),
            ]
        )
        result = repair.repair(self.smm_dir)
        self.assertEqual(result["malformed"], 1)
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["retained"], 2)

    def test_repair_single_pass_no_double_parse(self):
        """repair() parses each line exactly once.

        This is the structural form of the old repair scale timer: a second parse
        pass doubles the count here, deterministically, on any machine at any
        load — where the wall-clock bound could only notice it as a slowdown, and
        only if the box happened to be quiet.
        """
        import repair

        # Verify parse_jsonl is not imported (single-pass, no double parse)
        self.assertFalse(
            hasattr(repair, "parse_jsonl"),
            "repair should not import parse_jsonl",
        )

        e1 = make_event(content="good")
        lines = [json.dumps(e1), "bad json", '"a string"']
        self._write_raw_lines(lines)

        # Patch repair's reference to json — not the json module itself, which
        # the whole suite shares.
        spy = _CountingJson()
        with patch.object(repair, "json", spy):
            result = repair.repair(self.smm_dir, dry_run=True)

        self.assertEqual(
            spy.loads_calls,
            len(lines),
            f"repair parsed {spy.loads_calls} times for {len(lines)} lines — "
            "each line must be parsed exactly once",
        )
        self.assertEqual(result["malformed"], 1)
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["retained"], 1)

    def test_reads_events_under_lock(self):
        """repair() uses read_with_lock, not unlocked read_text."""
        import repair

        self._write_events([make_event()])

        called = {"count": 0}
        original_rwl = _append_impl.read_with_lock

        def tracking_rwl(path):
            called["count"] += 1
            return original_rwl(path)

        repair.read_with_lock = tracking_rwl
        try:
            repair.repair(self.smm_dir)
        finally:
            repair.read_with_lock = original_rwl

        self.assertEqual(called["count"], 1, "read_with_lock should be called once")


# ===========================================================================
# Migrate (Milestone 8)
# ===========================================================================


class TestMigrate(_SMMTestCase):
    """Tests for smm/migrate.py schema versioning."""

    def test_migrate_event_v1_to_v2(self):
        import migrate

        event = make_event(ts="2026-03-12T00:00:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 2)
        # Timestamp should have timezone
        self.assertIn("+", result["ts"])

    def test_migrate_event_already_v2(self):
        import migrate

        event = make_event(schema_version=2, ts="2026-03-12T00:00:00+00:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["ts"], "2026-03-12T00:00:00+00:00")

    def test_migrate_event_future_version_passthrough(self):
        """Events with schema_version > CURRENT pass through unchanged."""
        import migrate

        event = make_event(schema_version=99, ts="2026-03-12T00:00:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 99)
        # Should not modify the event
        self.assertEqual(result["ts"], "2026-03-12T00:00:00")

    def test_migrate_event_no_version_treated_as_v1(self):
        import migrate

        event = make_event()
        del event["schema_version"]
        result = migrate.migrate_event(event)
        self.assertEqual(result["schema_version"], 2)

    def test_migrate_file(self):
        import migrate

        events = [
            make_event(ts="2026-03-12T00:00:00"),
            make_event(ts="2026-03-13T00:00:00+00:00", schema_version=2),
        ]
        self._write_events(events)
        result = migrate.migrate_file(self.smm_dir)
        self.assertEqual(result["migrated"], 1)
        self.assertEqual(result["unchanged"], 1)
        # Read back and verify
        migrated = self._read_events()
        for e in migrated:
            self.assertEqual(e["schema_version"], 2)

    def test_migrate_file_idempotent(self):
        import migrate

        events = [make_event(ts="2026-03-12T00:00:00")]
        self._write_events(events)
        migrate.migrate_file(self.smm_dir)
        result = migrate.migrate_file(self.smm_dir)
        self.assertEqual(result["migrated"], 0)
        self.assertEqual(result["unchanged"], 1)

    def test_migrate_file_empty(self):
        import migrate

        result = migrate.migrate_file(self.smm_dir)
        self.assertEqual(result["migrated"], 0)
        self.assertEqual(result["unchanged"], 0)

    def test_migrate_preserves_all_fields(self):
        import migrate

        event = make_event(
            EVENT_TYPE_DECISION,
            topic="api",
            content="Use REST",
            ts="2026-03-12T00:00:00",
            references=["abc"],
            metadata={"notes": "from plan review"},
        )
        result = migrate.migrate_event(event)
        self.assertEqual(result["topic"], "api")
        self.assertEqual(result["content"], "Use REST")
        self.assertEqual(result["references"], ["abc"])
        self.assertEqual(result["metadata"], {"notes": "from plan review"})

    def test_migrate_ts_with_timezone_unchanged(self):
        """Timestamps that already have timezone info are not modified."""
        import migrate

        event = make_event(ts="2026-03-12T10:30:00-05:00")
        result = migrate.migrate_event(event)
        self.assertEqual(result["ts"], "2026-03-12T10:30:00-05:00")

    def test_reads_events_under_lock(self):
        """migrate_file() uses read_with_lock, not unlocked read_text."""
        import migrate

        self._write_events([make_event(ts="2026-03-12T00:00:00")])

        called = {"count": 0}
        original_rwl = _append_impl.read_with_lock

        def tracking_rwl(path):
            called["count"] += 1
            return original_rwl(path)

        migrate.read_with_lock = tracking_rwl
        try:
            migrate.migrate_file(self.smm_dir)
        finally:
            migrate.read_with_lock = original_rwl

        self.assertEqual(called["count"], 1, "read_with_lock should be called once")


if __name__ == "__main__":
    unittest.main()
