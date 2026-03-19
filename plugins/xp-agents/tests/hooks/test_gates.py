#!/usr/bin/env python3
"""Tests for Stop gate hooks: simplify_gate, quality_review_gate, tdd_stop_gate.

Also includes security helpers from _common.py.

Split from the monolithic test_hooks.py.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        inp = _make_stop_input()
        result = self.mod.run(inp, smm_dir=self.smm_dir)
        self.assertIsNotNone(result)

    def test_file_changes_triggers_simplify(self):
        self._write_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote file", working_on=["src/app.ts"]),
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
                make_event("status", content="wrote file", working_on=["src/app.ts"]),
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
                make_event("status", content="wrote", working_on=["src/a.ts"]),
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
                make_event("status", content="wrote", working_on=["src/a.ts"]),
                ci2,
                make_event("status", content="wrote2", working_on=["src/b.ts"]),
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
                make_event("status", content="wrote", working_on=["src/x.ts"]),
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
# Security helpers (_common.py) — Milestone 5.5
# ===========================================================================


class TestSecurityHelpers(_HookTestCase):
    """Tests for security review tracker helpers in _common.py."""

    def test_get_head_hash_returns_hash(self):
        """get_head_hash returns a hex hash string."""
        with patch(
            "security.subprocess.check_output",
            return_value="abc1234def5678\n",
        ):
            result = security.get_head_hash()
            self.assertEqual(result, "abc1234def5678")

    def test_get_head_hash_returns_none_on_error(self):
        """get_head_hash returns None when git fails."""
        from subprocess import CalledProcessError

        with patch(
            "security.subprocess.check_output",
            side_effect=CalledProcessError(128, "git"),
        ):
            result = security.get_head_hash()
            self.assertIsNone(result)

    def test_get_head_hash_returns_none_on_timeout(self):
        """get_head_hash returns None on subprocess timeout."""
        from subprocess import TimeoutExpired

        with patch(
            "security.subprocess.check_output",
            side_effect=TimeoutExpired("git", 5),
        ):
            result = security.get_head_hash()
            self.assertIsNone(result)

    def test_security_tracker_path_valid_hash(self):
        """security_tracker_path builds correct path for valid hash."""
        path = security.security_tracker_path(self.smm_dir, "abc1234")
        self.assertEqual(path, self.smm_dir / ".security-reviewed-abc1234")

    def test_security_tracker_path_rejects_invalid_hash(self):
        """security_tracker_path raises ValueError for invalid hash."""
        with self.assertRaises(ValueError):
            security.security_tracker_path(self.smm_dir, "not-a-hash!")
        with self.assertRaises(ValueError):
            security.security_tracker_path(self.smm_dir, "../etc/passwd")
        with self.assertRaises(ValueError):
            security.security_tracker_path(self.smm_dir, "")

    def test_security_tracker_path_rejects_too_short_hash(self):
        """security_tracker_path rejects hashes shorter than 7 chars."""
        with self.assertRaises(ValueError):
            security.security_tracker_path(self.smm_dir, "abc12")

    def test_write_and_exists_tracker(self):
        """write_security_tracker creates file, security_tracker_exists finds it."""
        security.write_security_tracker(self.smm_dir, "abc1234")
        self.assertTrue(security.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_tracker_not_exists_when_missing(self):
        """security_tracker_exists returns False when no tracker file."""
        self.assertFalse(security.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_write_tracker_cleans_old(self):
        """write_security_tracker removes old tracker files."""
        security.write_security_tracker(self.smm_dir, "aaa1111")
        security.write_security_tracker(self.smm_dir, "bbb2222")
        # Write new tracker
        security.write_security_tracker(self.smm_dir, "ccc3333")
        self.assertFalse(security.security_tracker_exists(self.smm_dir, "aaa1111"))
        self.assertFalse(security.security_tracker_exists(self.smm_dir, "bbb2222"))
        self.assertTrue(security.security_tracker_exists(self.smm_dir, "ccc3333"))

    def test_tracker_rejects_symlink(self):
        """security_tracker_exists returns False for symlinks."""
        real_file = self.smm_dir / "real_target"
        real_file.write_text("x")
        link = self.smm_dir / ".security-reviewed-abc1234"
        link.symlink_to(real_file)
        self.assertFalse(security.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_cleanup_skips_non_hash_files(self):
        """_cleanup_old_security_trackers skips files with non-hash suffixes."""
        notes = self.smm_dir / ".security-reviewed-notes.txt"
        notes.write_text("keep me")
        security.write_security_tracker(self.smm_dir, "abc1234")
        self.assertTrue(notes.exists(), "Non-hash file should survive cleanup")

    def test_mark_security_reviewed(self):
        """mark_security_reviewed encapsulates hash fetch + tracker write."""
        with patch.object(security, "get_head_hash", return_value="abc1234"):
            security.mark_security_reviewed(self.smm_dir)
        self.assertTrue(security.security_tracker_exists(self.smm_dir, "abc1234"))

    def test_mark_security_reviewed_no_hash(self):
        """mark_security_reviewed no-ops when HEAD hash unavailable."""
        with patch.object(security, "get_head_hash", return_value=None):
            security.mark_security_reviewed(self.smm_dir)
        # No tracker, no crash

    def test_write_tracker_content(self):
        """write_security_tracker writes JSON with commit_hash and ts."""
        security.write_security_tracker(self.smm_dir, "abc1234")
        path = security.security_tracker_path(self.smm_dir, "abc1234")
        data = json.loads(path.read_text())
        self.assertEqual(data["commit_hash"], "abc1234")
        self.assertIn("ts", data)


if __name__ == "__main__":
    unittest.main()
