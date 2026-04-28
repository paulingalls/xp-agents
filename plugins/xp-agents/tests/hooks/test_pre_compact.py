#!/usr/bin/env python3
"""Tests for pre_compact.py — backup of events.jsonl and SMM before compaction."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import smm_schema
import smm_store
from conftest import _HookTestCase, make_event


class TestPreCompact(_HookTestCase):
    def test_xp_agent_skips(self):
        import pre_compact

        result = pre_compact.run(
            {"session_id": "test", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_missing_smm_dir(self):
        import pre_compact

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        result = pre_compact.run(
            {"session_id": "test"},
            smm_dir=fake_dir,
        )
        self.assertIsNone(result)

    def test_creates_backup_of_events(self):
        import pre_compact

        self._write_events([make_event()])
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backups = list((self.smm_dir / "backups").glob("events-*.jsonl"))
        self.assertEqual(len(backups), 1)

    def test_creates_backup_of_smm(self):
        import pre_compact

        self._write_events([make_event()])
        smm_store.save_smm(self.smm_dir, smm_schema.empty_smm())
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backups = list((self.smm_dir / "backups").glob("SMM-*.json"))
        self.assertEqual(len(backups), 1)

    def test_backup_content_matches(self):
        import pre_compact

        events = [make_event()]
        self._write_events(events)
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backup = next(iter((self.smm_dir / "backups").glob("events-*.jsonl")))
        original = self.events_file.read_text()
        self.assertEqual(backup.read_text(), original)

    def test_no_smm_file_only_events_backed_up(self):
        import pre_compact

        self._write_events([make_event()])
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        event_backups = list((self.smm_dir / "backups").glob("events-*.jsonl"))
        smm_backups = list((self.smm_dir / "backups").glob("SMM-*.json"))
        self.assertEqual(len(event_backups), 1)
        self.assertEqual(len(smm_backups), 0)

    def test_timestamp_in_backup_name(self):
        import pre_compact

        self._write_events([make_event()])
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        backup = next(iter((self.smm_dir / "backups").glob("events-*.jsonl")))
        # Name should be events-YYYYMMDD-HHMMSS.jsonl
        name = backup.stem  # events-YYYYMMDD-HHMMSS
        parts = name.split("-", 1)
        self.assertEqual(parts[0], "events")
        self.assertTrue(len(parts[1]) > 0)

    def test_backup_rotation_caps_old_backups(self):
        import pre_compact

        self._write_events([make_event()])
        backups_dir = self.smm_dir / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        # Create 12 fake old backups
        for i in range(12):
            (backups_dir / f"events-20250101-{i:06d}.jsonl").write_text("old")
        pre_compact.run({"session_id": "test"}, smm_dir=self.smm_dir)
        # After rotation, should have at most _MAX_BACKUPS (10)
        remaining = list(backups_dir.glob("events-*.jsonl"))
        self.assertLessEqual(len(remaining), pre_compact._MAX_BACKUPS)


if __name__ == "__main__":
    unittest.main()
