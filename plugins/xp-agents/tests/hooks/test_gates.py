#!/usr/bin/env python3
"""Tests for Stop gate hooks: simplify_gate, quality_review_gate, tdd_stop_gate.

Also includes security helpers from _common.py.

Split from the monolithic test_hooks.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import quality_review_gate
import security
from conftest import _HookTestCase, make_event

# ===========================================================================
# Helpers for Stop hook tests
# ===========================================================================


def _make_stop_input(**overrides) -> dict:
    """Build a canonical Stop hook input dict."""
    data = {"session_id": "t", "agent_id": "main"}
    data.update(overrides)
    return data


# ===========================================================================
# Simplify Gate (Milestone 5.4)
# ===========================================================================


class TestSimplifyGate(_HookTestCase):
    """Tests for simplify_gate.py Stop command hook."""

    def setUp(self):
        super().setUp()
        import simplify_gate

        self.mod = simplify_gate

    def test_xp_agent_skips(self):
        inp = _make_stop_input(agent_type="xp-nav")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_stop_hook_active_skips(self):
        inp = _make_stop_input(stop_hook_active=True)
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_smm_dir_degrades(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        self.assertIsNone(result)

    def test_no_events_no_output(self):
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_customer_input_no_output(self):
        self._write_events([make_event("status", content="busy")])
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_file_changes_no_output(self):
        self._write_events(
            [
                make_event("customer_input", content="do something"),
                make_event("status", content="thinking", working_on=[]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_docs_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="update docs"),
                make_event("status", content="wrote", working_on=["README.md"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_config_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="update config"),
                make_event("status", content="wrote", working_on=["package.json"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_only_images_no_trigger(self):
        self._write_events(
            [
                make_event("customer_input", content="add logo"),
                make_event("status", content="wrote", working_on=["logo.png"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_code_plus_docs_triggers(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote", working_on=["README.md"]),
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_file_changes_triggers_simplify(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event(
                    "status",
                    content="wrote file",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

    def test_tracker_prevents_retrigger(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event(
                    "status",
                    content="wrote file",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)
        # Second call — tracker should prevent re-trigger
        result2 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result2)

    def test_new_loop_resets_tracker(self):
        ci1 = make_event("customer_input", content="first task")
        self._write_events(
            [
                ci1,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/a.ts", "src/b.ts", "src/c.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        result1 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result1)

        # New loop: new customer_input + changes
        ci2 = make_event("customer_input", content="second task")
        self._write_events(
            [
                ci1,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/a.ts", "src/b.ts", "src/c.ts"],
                ),
                ci2,
                make_event(
                    "status",
                    content="wrote2",
                    working_on=["src/d.ts", "src/e.ts", "src/f.ts"],
                ),
            ]
        )
        result2 = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result2)
        self.assertIn("/simplify", result2)

    def test_tracker_written_with_loop_id(self):
        ci = make_event("customer_input", content="build")
        self._write_events(
            [
                ci,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/x.ts", "src/y.ts", "src/z.ts"],
                ),
            ]
        )
        inp = _make_stop_input()
        self.mod.run(inp, smm_dir=self.smm_dir)

        tracker_file = self.smm_dir / ".simplify-main.json"
        self.assertTrue(tracker_file.exists())
        tracker = json.loads(tracker_file.read_text())
        self.assertEqual(tracker["loop_id"], ci["id"])


# ===========================================================================
# Security: agent_id validation + symlink protection
# ===========================================================================


class TestSimplifyGateSecurity(_HookTestCase):
    """Security tests for simplify_gate.py."""

    def setUp(self):
        super().setUp()
        import simplify_gate

        self.mod = simplify_gate

    def test_path_traversal_agent_id_rejected(self):
        """agent_id with path traversal is rejected."""
        self._write_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/a.ts"]),
            ]
        )
        inp = _make_stop_input(agent_id="../../../etc/evil")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_slash_agent_id_rejected(self):
        self._write_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/a.ts"]),
            ]
        )
        inp = _make_stop_input(agent_id="foo/bar")
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)


# ===========================================================================
# Quality Review Gate
# ===========================================================================


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


# ===========================================================================
# Security triage marker helpers — replaces hash-based tracker
# ===========================================================================


class TestSecurityTriageMarker(_HookTestCase):
    """Tests for security triage marker helpers in security.py."""

    def test_triaged_path(self):
        """security_triaged_path returns correct path."""
        path = security.security_triaged_path(self.smm_dir)
        self.assertEqual(path, self.smm_dir / ".security-triaged")

    def test_write_and_exists(self):
        """write_security_triaged creates file, security_triaged_exists finds it."""
        security.write_security_triaged(self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))

    def test_not_exists_when_missing(self):
        """security_triaged_exists returns False when no marker file."""
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_consume_deletes_marker(self):
        """consume_security_triaged removes the marker."""
        security.write_security_triaged(self.smm_dir)
        self.assertTrue(security.security_triaged_exists(self.smm_dir))
        security.consume_security_triaged(self.smm_dir)
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_consume_no_op_when_missing(self):
        """consume_security_triaged is safe when marker doesn't exist."""
        security.consume_security_triaged(self.smm_dir)  # no crash

    def test_rejects_symlink(self):
        """security_triaged_exists returns False for symlinks."""
        real_file = self.smm_dir / "real_target"
        real_file.write_text("x")
        link = security.security_triaged_path(self.smm_dir)
        link.symlink_to(real_file)
        self.assertFalse(security.security_triaged_exists(self.smm_dir))

    def test_write_marker_content(self):
        """write_security_triaged writes JSON with ts."""
        security.write_security_triaged(self.smm_dir)
        path = security.security_triaged_path(self.smm_dir)
        data = json.loads(path.read_text())
        self.assertIn("ts", data)


if __name__ == "__main__":
    unittest.main()
