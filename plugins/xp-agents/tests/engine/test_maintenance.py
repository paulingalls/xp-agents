#!/usr/bin/env python3
"""Tests for repair, migration, and performance benchmarks.

Split from smm/test_engine.py — covers:
  TestRepair, TestMigrate, TestPerformanceBenchmarks.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
import read_delta
from conftest import _SMMTestCase, make_event
from event_schema import EVENT_TYPE_DECISION, EVENT_TYPE_SESSION_END, EVENT_TYPE_STATUS

# ===========================================================================
# Repair (Milestone 8)
# ===========================================================================


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
        """repair() uses single-pass — no parse_jsonl import needed."""
        import repair

        # Verify parse_jsonl is not imported (single-pass, no double parse)
        self.assertFalse(
            hasattr(repair, "parse_jsonl"),
            "repair should not import parse_jsonl",
        )

        e1 = make_event(content="good")
        self._write_raw_lines([json.dumps(e1), "bad json", '"a string"'])
        result = repair.repair(self.smm_dir, dry_run=True)
        self.assertEqual(result["malformed"], 1)
        self.assertEqual(result["invalid"], 1)
        self.assertEqual(result["retained"], 1)


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


# ===========================================================================
# Performance Benchmarks (Milestone 8)
# ===========================================================================


def _generate_mixed_events(count: int) -> list[dict]:
    """Generate a realistic distribution of events."""
    import random

    rng = random.Random(42)  # deterministic for reproducibility
    type_weights = [
        ("customer_input", 25),
        ("status", 20),
        ("decision", 8),
        ("convention", 5),
        ("concern", 8),
        ("discovery", 5),
        ("question", 8),
        ("answer", 5),
        ("assumption", 4),
        ("session_end", 2),
        ("goal", 1),
        ("debt", 1),
    ]
    types = []
    for t, w in type_weights:
        types.extend([t] * w)

    events = []
    for i in range(count):
        etype = rng.choice(types)
        ts = f"2026-01-01T{i // 3600:02d}:{(i % 3600) // 60:02d}:{i % 60:02d}+00:00"
        events.append(make_event(etype, content=f"event-{i}", ts=ts))
    return events


class TestPerformanceBenchmarks(_SMMTestCase):
    """Performance benchmark tests for M8."""

    def test_read_delta_1000_with_watermark(self):
        import time

        events = _generate_mixed_events(1000)
        self._write_events(events)
        read_delta.write_watermark(self.smm_dir, "bench", 500)
        start = time.monotonic()
        read_delta.read_delta(self.smm_dir, "bench")
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(
            elapsed, 50, f"read_delta(1000@500) took {elapsed:.0f}ms > 50ms"
        )

    def test_compact_5000_events(self):
        import time

        import compact

        events = _generate_mixed_events(5000)
        # Add session_end events at regular intervals
        for i in range(10):
            events.append(
                make_event(
                    EVENT_TYPE_SESSION_END,
                    content=f"end-{i}",
                    working_on=[],
                    ts=f"2026-02-{i + 1:02d}T00:00:00+00:00",
                )
            )
        self._write_events(events)
        start = time.monotonic()
        compact.compact(self.smm_dir, keep_sessions=3)
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(elapsed, 1000, f"compact(5000) took {elapsed:.0f}ms > 1000ms")

    def test_repair_5000_events(self):
        import time

        import repair

        events = _generate_mixed_events(5000)
        self._write_events(events)
        start = time.monotonic()
        repair.repair(self.smm_dir)
        elapsed = (time.monotonic() - start) * 1000
        self.assertLess(elapsed, 1000, f"repair(5000) took {elapsed:.0f}ms > 1000ms")

    def test_mixed_event_generator_distribution(self):
        """Verify _generate_mixed_events produces expected types."""
        events = _generate_mixed_events(100)
        types = {e["type"] for e in events}
        # Should have at least a few different types
        self.assertGreater(len(types), 5)
        # All should be valid events
        for e in events:
            self.assertIn("id", e)
            self.assertIn("type", e)


if __name__ == "__main__":
    unittest.main()
