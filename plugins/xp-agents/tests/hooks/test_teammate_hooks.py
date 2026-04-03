#!/usr/bin/env python3
"""Tests for teammate_idle.py and task_completed.py hooks (M13)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _HookTestCase,
    _make_task_completed_input,
    _make_teammate_idle_input,
    make_event,
)

# ===========================================================================
# teammate_idle.py — TeammateIdle TDD gate
# ===========================================================================


class TestTeammateIdle(_HookTestCase):
    """M13: TeammateIdle blocks when tests are failing."""

    def test_blocks_on_failing_tests(self):
        import teammate_idle

        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        result = teammate_idle.run(_make_teammate_idle_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("failing", result.lower())

    def test_allows_on_passing_tests(self):
        import teammate_idle

        self._write_events(
            [
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
            ]
        )
        result = teammate_idle.run(_make_teammate_idle_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_teammate_name_skips(self):
        """Events without teammate_name are not teammate events — skip."""
        import teammate_idle

        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        inp = {"session_id": "t"}  # No teammate_name
        result = teammate_idle.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_graceful(self):
        import teammate_idle

        result = teammate_idle.run(
            _make_teammate_idle_input(),
            smm_dir=Path("/nonexistent/smm"),
        )
        self.assertIsNone(result)

    def test_no_events_allows(self):
        import teammate_idle

        result = teammate_idle.run(_make_teammate_idle_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_resolved_failure_allows(self):
        import teammate_idle

        fail = make_event(
            "concern",
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        resolution = make_event(
            "status",
            content="Resolved",
            working_on=[],
            metadata={"resolves": [fail["id"]]},
        )
        self._write_events([fail, resolution])
        result = teammate_idle.run(_make_teammate_idle_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)


# ===========================================================================
# task_completed.py — TaskCompleted TDD gate
# ===========================================================================


class TestTaskCompleted(_HookTestCase):
    """M13: TaskCompleted blocks when tests are failing."""

    def test_blocks_on_failing_tests(self):
        import task_completed

        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        result = task_completed.run(_make_task_completed_input(), smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("failing", result.lower())

    def test_allows_on_passing_tests(self):
        import task_completed

        self._write_events(
            [
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
            ]
        )
        result = task_completed.run(_make_task_completed_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_teammate_name_skips(self):
        import task_completed

        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        inp = {"session_id": "t", "task_id": "t-1"}  # No teammate_name
        result = task_completed.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_graceful(self):
        import task_completed

        result = task_completed.run(
            _make_task_completed_input(),
            smm_dir=Path("/nonexistent/smm"),
        )
        self.assertIsNone(result)

    def test_no_events_allows(self):
        import task_completed

        result = task_completed.run(_make_task_completed_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_resolved_failure_allows(self):
        import task_completed

        fail = make_event(
            "concern",
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        resolution = make_event(
            "status",
            content="Resolved",
            working_on=[],
            metadata={"resolves": [fail["id"]]},
        )
        self._write_events([fail, resolution])
        result = task_completed.run(_make_task_completed_input(), smm_dir=self.smm_dir)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
