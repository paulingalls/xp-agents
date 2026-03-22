#!/usr/bin/env python3
"""Tests for quality_review_gate.py and tdd_stop_gate.py Stop hooks.

Split from test_gates.py for file size management.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import quality_review_gate
from conftest import _HookTestCase, make_event


def _make_stop_input(**overrides) -> dict:
    """Build a canonical Stop hook input dict."""
    data = {"session_id": "t", "agent_id": "main"}
    data.update(overrides)
    return data


class TestQualityReviewGate(_HookTestCase):
    """Tests for quality_review_gate.py Stop command hook."""

    def setUp(self):
        super().setUp()
        self.mod = quality_review_gate

    def _seed_simplify_done(self, loop_id: str) -> None:
        """Write a simplify tracker showing simplify completed for loop_id."""
        tracker = self.smm_dir / ".simplify-main.json"
        tracker.write_text(json.dumps({"loop_id": loop_id}))

    def test_xp_agent_skips(self):
        inp = _make_stop_input(agent_type="xp-nav")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_degrades(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_no_events_passes(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_simplify_tracker_passes(self):
        """If simplify hasn't run yet, quality gate stays silent."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_simplify_done_blocks(self):
        """After simplify runs, quality gate blocks."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_tracker_prevents_retrigger(self):
        """Second call after quality review gate fires passes."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)
        # Second call — tracker prevents re-trigger
        result2 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result2)

    def test_simplify_tracker_wrong_loop_passes(self):
        """Simplify tracker from a different loop doesn't trigger gate."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        self._seed_simplify_done("different-loop-id")
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_non_code_changes_pass(self):
        """Only docs/config modified — quality gate doesn't fire."""
        ci = make_event("customer_input", content="update docs")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["README.md"]),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_tracker_written_with_loop_id(self):
        """Quality review tracker file has correct structure."""
        ci = make_event("customer_input", content="build")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/x.ts"]),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        self.mod.run(inp, smm_dir=self.smm_dir)

        tracker_file = self.smm_dir / ".quality-review-main.json"
        self.assertTrue(tracker_file.exists())
        tracker = json.loads(tracker_file.read_text())
        self.assertEqual(tracker["loop_id"], ci["id"])


class TestQualityReviewPendingSubagents(_HookTestCase):
    """Tests for quality_review_gate pending-subagent detection."""

    def setUp(self):
        super().setUp()
        self.mod = quality_review_gate

    def _seed_simplify_done(self, loop_id: str) -> None:
        tracker = self.smm_dir / ".simplify-main.json"
        tracker.write_text(json.dumps({"loop_id": loop_id}))

    def test_pending_subagents_lets_stop_through(self):
        """Gate returns None (no block) while subagents are still running."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 started",
                    working_on=[],
                ),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_all_completed_fires_quality_review(self):
        """Gate proceeds to quality review when all subagents completed."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 started",
                    working_on=[],
                ),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 completed",
                    working_on=[],
                ),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_no_subagents_fires_quality_review(self):
        """No subagent events = normal quality review flow."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_stop_hook_active_pending_lets_through(self):
        """Gate returns None for pending subagents even with stop_hook_active=True."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 started",
                    working_on=[],
                ),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input(stop_hook_active=True)
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_stop_hook_active_with_completed_allows_quality_check(self):
        """stop_hook_active + all completed → tracker already written → passes."""
        ci = make_event("customer_input", content="build feature")
        self._write_events(
            [
                ci,
                make_event("status", content="wrote", working_on=["src/app.ts"]),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 started",
                    working_on=[],
                ),
                make_event(
                    "status",
                    agent_id="explorer-1",
                    content="Subagent explorer-1 completed",
                    working_on=[],
                ),
            ]
        )
        self._seed_simplify_done(ci["id"])
        inp = _make_stop_input()
        # First call writes tracker and blocks with quality review message
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)
        self.assertIn("/xp-quality-review", result1)
        # Second call (stop_hook_active=True) — tracker prevents re-trigger
        inp2 = _make_stop_input(stop_hook_active=True)
        result2 = self.mod.run(inp2, smm_dir=self.smm_dir)
        self.assertIsNone(result2)


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


if __name__ == "__main__":
    unittest.main()
