#!/usr/bin/env python3
"""Tests for tdd_stop_gate.py Stop hook.

Quality review gate tests removed in M3 (commit-gated review cycle replaces Stop gates).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _make_stop_input, make_event

# ===========================================================================
# TDD Stop Gate (replaces tdd_check.md prompt hook)
# ===========================================================================


class TestTddStopGate(_HookTestCase):
    """Tests for tdd_stop_gate.py Stop command hook."""

    def setUp(self):
        super().setUp()
        import tdd_stop_gate

        self.mod = tdd_stop_gate

    def test_xp_agent_skips(self):
        inp = _make_stop_input(agent_type="xp-nav")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_stop_hook_active_skips(self):
        inp = _make_stop_input(stop_hook_active=True)
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_events_allows_stop(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_degrades(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_passing_tests_allows_stop(self):
        self._write_events(
            [
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_failing_tests_blocks_stop(self):
        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("failing", result.lower())

    def test_failed_test_run_blocks_stop(self):
        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test command failed: `pytest` — exit 1",
                    severity="high",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_pass_after_fail_allows_stop(self):
        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_fail_after_pass_blocks_stop(self):
        self._write_events(
            [
                make_event(
                    "status",
                    content="Tests: 5 passed, 0 failed (pytest)",
                ),
                make_event(
                    "concern",
                    content="Test failures detected: 1 failed (jest)",
                    severity="high",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_no_test_events_allows_stop(self):
        self._write_events(
            [
                make_event("status", content="Wrote file", working_on=["a.py"]),
                make_event("customer_input", content="build something"),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_fallback_pass_format_allows_stop(self):
        """'Tests passed (framework)' fallback format should be recognized as pass."""
        self._write_events(
            [
                make_event(
                    "concern",
                    content="Test failures detected: 1 failed (pytest)",
                    severity="high",
                ),
                make_event(
                    "status",
                    content="Tests passed (pytest)",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_resolved_concern_allows_stop(self):
        """A resolved test failure concern should not block stop."""
        fail = make_event(
            "concern",
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        resolution = make_event(
            "status",
            content="Test concern resolved: Test failures detected: 2 failed",
            working_on=[],
            metadata={"resolves": [fail["id"]]},
        )
        self._write_events([fail, resolution])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_ambiguous_test_result_allows_stop(self):
        """Neutral test status (counts not extracted) should not block stop."""
        self._write_events(
            [
                make_event(
                    "status",
                    content="Tests ran (pytest) — counts not extracted",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)


# ===========================================================================
# Session End Warning (soft warning, not a block)
# ===========================================================================


class TestSessionEndWarning(_HookTestCase):
    """Tests for session_end_warning.py Stop command hook."""

    def setUp(self):
        super().setUp()
        import session_end_warning

        self.mod = session_end_warning

    def test_xp_agent_skips(self):
        inp = _make_stop_input(agent_type="xp-retro")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_events_no_warning(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_degrades(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_unresolved_concerns_warns(self):
        """Unresolved concerns produce a soft warning."""
        self._write_events(
            [
                make_event("concern", content="Something is wrong", severity="medium"),
                make_event("concern", content="Another issue", severity="low"),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("2", result)
        self.assertIn("concern", result.lower())

    def test_resolved_concerns_no_warning(self):
        """Resolved concerns do not trigger a warning."""
        concern = make_event("concern", content="Fixed issue", severity="medium")
        resolve = make_event(
            "status",
            content="Resolved: Fixed issue",
            metadata={"resolves": [concern["id"]]},
        )
        self._write_events([concern, resolve])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_missing_final_status_warns(self):
        """No recent status from main agent produces a reminder."""
        self._write_events(
            [
                make_event("customer_input", content="Build something"),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("session-end status", result.lower())

    def test_recent_status_no_reminder(self):
        """Recent status from main agent suppresses the reminder."""
        self._write_events(
            [
                make_event(
                    "status",
                    content="Completed M9 implementation",
                    agent_id="main",
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_both_issues_combined(self):
        """Both unresolved concerns and missing status produce one warning."""
        self._write_events(
            [
                make_event("concern", content="Open issue", severity="medium"),
                make_event("customer_input", content="Last input"),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("concern", result.lower())
        self.assertIn("session-end status", result.lower())


# ===========================================================================
# Shared TDD check (tdd_check.py)
# ===========================================================================


class TestFindLastTestSignal(_HookTestCase):
    """M13: shared find_last_test_signal extracted from tdd_stop_gate."""

    def test_pass_event(self):
        """Returns 'pass' for passing test status event."""
        from tdd_check import find_last_test_signal

        events = [make_event("status", content="Tests: 5 passed, 0 failed (pytest)")]
        self.assertEqual(find_last_test_signal(events), "pass")

    def test_fail_event(self):
        """Returns 'fail' for unresolved test failure concern."""
        from tdd_check import find_last_test_signal

        events = [
            make_event(
                "concern",
                content="Test failures detected: 2 failed (pytest)",
                severity="high",
            )
        ]
        self.assertEqual(find_last_test_signal(events), "fail")

    def test_resolved_concern_skipped(self):
        """Resolved test failure does not return 'fail'."""
        from tdd_check import find_last_test_signal

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
        self.assertIsNone(find_last_test_signal([fail, resolution]))

    def test_no_events(self):
        """Returns None for empty event list."""
        from tdd_check import find_last_test_signal

        self.assertIsNone(find_last_test_signal([]))

    def test_fallback_pass_format(self):
        """'Tests passed' fallback format recognized."""
        from tdd_check import find_last_test_signal

        events = [make_event("status", content="Tests passed (unittest)")]
        self.assertEqual(find_last_test_signal(events), "pass")


if __name__ == "__main__":
    unittest.main()
