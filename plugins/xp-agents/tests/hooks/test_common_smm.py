#!/usr/bin/env python3
"""Tests for SMM event reading, decision finding, budgets, and concern helpers.

Split from test_common.py. Conflict detection tests in test_common_conflicts.py.
Lookup/utility tests in test_common_smm_lookups.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import concerns
from conftest import _HookTestCase, make_event


class TestReadEventsRaw(_HookTestCase):
    def test_reads_valid_events(self):
        events = [make_event(), make_event("status")]
        self._write_events(events)
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(result), 2)

    def test_skips_malformed_lines(self):
        self._write_raw_lines(
            [json.dumps(make_event()), "bad line", json.dumps(make_event())]
        )
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(result), 2)

    def test_empty_file(self):
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(result, [])

    def test_missing_file(self):
        self.events_file.unlink()
        result = _common.read_events_raw(self.smm_dir)
        self.assertEqual(result, [])


class TestFindRelatedDecisions(unittest.TestCase):
    """Test concerns.find_related_decisions correctness."""

    def test_matches_via_working_on(self):
        d = make_event(
            "decision", topic="auth", content="Use JWT", working_on=["/tmp/src/auth.ts"]
        )
        result = concerns.find_related_decisions([d], "/tmp/src/auth.ts", "/tmp")
        self.assertIn(d["id"], result)

    def test_no_match_different_file(self):
        d = make_event(
            "decision", topic="auth", content="Use JWT", working_on=["/tmp/src/auth.ts"]
        )
        result = concerns.find_related_decisions([d], "/tmp/src/other.ts", "/tmp")
        self.assertNotIn(d["id"], result)

    def test_no_substring_false_positive_via_references(self):
        """'a.py' must not match a reference to 'data.py'."""
        d = make_event(
            "decision",
            topic="naming",
            content="Naming convention",
            references=["data.py"],
        )
        result = concerns.find_related_decisions([d], "a.py", "/tmp")
        self.assertNotIn(d["id"], result)

    def test_exact_reference_match(self):
        """Exact normalized path in references should match."""
        d = make_event(
            "decision", topic="auth", content="Use JWT", references=["src/auth.ts"]
        )
        result = concerns.find_related_decisions([d], "src/auth.ts", "/tmp")
        self.assertIn(d["id"], result)

    def test_skips_non_decision_events(self):
        s = make_event("status", content="Working", working_on=["/tmp/src/app.ts"])
        result = concerns.find_related_decisions([s], "/tmp/src/app.ts", "/tmp")
        self.assertEqual(result, [])

    def test_invalid_agent_id_graceful(self):
        """Invalid agent_id in _validate_agent_id should not crash hooks."""
        import post_tool_use
        from conftest import _make_write_input

        result = post_tool_use.run(
            _make_write_input(
                tool_input={"file_path": "x.py", "content": "x"},
                agent_id="bad;agent",
            ),
        )
        self.assertIsNone(result)


class TestAppendSafeBudget(_HookTestCase):
    """Verify _common.append_safe drops over-budget events silently."""

    def test_append_safe_drops_over_budget(self):
        event = make_event("status", content="x" * 201, working_on=[])
        _common.append_safe(self.smm_dir, event)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_append_safe_writes_within_budget(self):
        event = make_event("status", content="x" * 200, working_on=[])
        _common.append_safe(self.smm_dir, event)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 1)


class TestMakeConcernFiles(unittest.TestCase):
    def test_make_concern_without_files(self):
        event = concerns.make_concern("bug found", "medium", "main")
        self.assertNotIn("files", event)

    def test_make_concern_with_files(self):
        event = concerns.make_concern(
            "lint error", "medium", "main", files=["scripts/foo.py"]
        )
        self.assertEqual(event["files"], ["scripts/foo.py"])

    def test_make_concern_empty_files_not_set(self):
        event = concerns.make_concern("bug", "low", "main", files=[])
        self.assertNotIn("files", event)

    def test_make_concern_with_references_and_files(self):
        event = concerns.make_concern(
            "issue",
            "high",
            "main",
            references=["abc123def456"],
            files=["scripts/bar.py"],
        )
        self.assertEqual(event["references"], ["abc123def456"])
        self.assertEqual(event["files"], ["scripts/bar.py"])


if __name__ == "__main__":
    unittest.main()
