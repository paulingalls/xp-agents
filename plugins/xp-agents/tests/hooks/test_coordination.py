#!/usr/bin/env python3
"""Tests for coordination file helpers and working-on overlap detection."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import coordination
import pre_tool_use
from conftest import _HookTestCase


class TestCoordination(_HookTestCase):
    """Test coordination file helpers: update, read, clear."""

    def test_update_creates_file(self):
        """update_coordination creates .coordination.json if missing."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coord_file = self.smm_dir / ".coordination.json"
        self.assertTrue(coord_file.exists())

    def test_update_adds_agent_entry(self):
        """Entry has working_on list and updated timestamp."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertIn("main", data)
        self.assertEqual(data["main"]["working_on"], ["src/a.ts"])
        self.assertIn("updated", data["main"])

    def test_update_overwrites_previous(self):
        """Latest update replaces previous working_on."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coordination.update_coordination(self.smm_dir, "main", ["src/b.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data["main"]["working_on"], ["src/b.ts"])

    def test_read_returns_empty_on_missing(self):
        """read_coordination returns {} when file doesn't exist."""
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data, {})

    def test_read_ignores_stale_entries(self):
        """Entries older than max_age_seconds are excluded."""
        from datetime import datetime, timedelta, timezone

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text(
            json.dumps(
                {
                    "stale-agent": {
                        "working_on": ["src/old.ts"],
                        "updated": old_time,
                    }
                }
            )
        )
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data, {})

    def test_read_keeps_fresh_entries(self):
        """Entries within max_age_seconds are kept."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        data = coordination.read_coordination(self.smm_dir)
        self.assertIn("main", data)

    def test_clear_removes_agent(self):
        """clear_coordination_agent removes the agent's entry."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coordination.clear_coordination_agent(self.smm_dir, "main")
        data = coordination.read_coordination(self.smm_dir)
        self.assertNotIn("main", data)

    def test_clear_preserves_others(self):
        """Clearing one agent doesn't affect other agents."""
        coordination.update_coordination(self.smm_dir, "main", ["src/a.ts"])
        coordination.update_coordination(self.smm_dir, "agent-2", ["src/b.ts"])
        coordination.clear_coordination_agent(self.smm_dir, "main")
        data = coordination.read_coordination(self.smm_dir)
        self.assertNotIn("main", data)
        self.assertIn("agent-2", data)

    def test_clear_noop_on_missing_file(self):
        """clear_coordination_agent is a no-op if file doesn't exist."""
        coordination.clear_coordination_agent(self.smm_dir, "main")
        # Should not raise

    def test_corrupted_file_returns_empty(self):
        """read_coordination returns {} on invalid JSON."""
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text("not json{{{")
        data = coordination.read_coordination(self.smm_dir)
        self.assertEqual(data, {})


class TestCheckWorkingOnOverlapCoordination(_HookTestCase):
    """Test overlap detection using .coordination.json."""

    def test_no_overlap(self):
        """No conflict when agents work on different files."""
        coordination.update_coordination(self.smm_dir, "other", ["src/b.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/a.ts", "/project"
        )
        self.assertIsNone(result)

    def test_overlap_detected(self):
        """Conflict detected when another agent works on the same file."""
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNotNone(result)
        self.assertIn("other", result)

    def test_self_overlap_ignored(self):
        """No conflict when the same agent works on the same file."""
        coordination.update_coordination(self.smm_dir, "main", ["src/app.ts"])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_stale_entry_ignored(self):
        """Stale coordination entries don't trigger conflicts."""
        from datetime import datetime, timedelta, timezone

        old_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
        coord_file = self.smm_dir / ".coordination.json"
        coord_file.write_text(
            json.dumps(
                {
                    "other": {
                        "working_on": ["src/app.ts"],
                        "updated": old_time,
                    }
                }
            )
        )
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_empty_working_on(self):
        """Agent with empty working_on doesn't trigger conflict."""
        coordination.update_coordination(self.smm_dir, "other", [])
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)

    def test_cleared_agent_no_conflict(self):
        """After clearing, agent no longer causes conflicts."""
        coordination.update_coordination(self.smm_dir, "other", ["src/app.ts"])
        coordination.clear_coordination_agent(self.smm_dir, "other")
        result = pre_tool_use.check_working_on_overlap(
            self.smm_dir, "main", "src/app.ts", "/project"
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
