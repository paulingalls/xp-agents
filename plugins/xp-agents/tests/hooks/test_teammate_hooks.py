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


# ===========================================================================
# teammate_stop_gate.py — Stop gate: review cycle + commit before stop
# ===========================================================================


def _make_teammate_stop_input(**overrides) -> dict:
    """Build a canonical Stop hook input for a CLI teammate."""
    data = {
        "session_id": "t",
        "cwd": "/proj/.claude/worktrees/worktree-story-1/src",
    }
    data.update(overrides)
    return data


class TestTeammateStopGate(_HookTestCase):
    """Stop gate blocks teammates without completed review cycle + commit."""

    def _set_review_flags(self, **flags):
        """Set review cycle marker flags for teammate-1."""
        import markers

        data = markers.read_review_cycle(self.smm_dir, "worktree-story-1")
        data.update(flags)
        markers.write_review_cycle(self.smm_dir, "worktree-story-1", data)

    def test_non_teammate_skips(self):
        """Non-teammate agent_type exits cleanly."""
        import teammate_stop_gate

        inp = _make_teammate_stop_input(agent_type="xp-plan-reviewer")
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_agent_type_no_worktree_skips(self):
        """Missing agent_type + non-worktree cwd exits cleanly."""
        import teammate_stop_gate

        inp = _make_teammate_stop_input(agent_type="", cwd="/tmp/regular")
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir)
        self.assertIsNone(result)

    def test_no_uncommitted_changes_allows_stop(self):
        """Teammate with no uncommitted changes can stop."""
        import teammate_stop_gate

        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=False,
        )
        self.assertIsNone(result)

    def test_uncommitted_no_review_blocks_simplify(self):
        """Uncommitted changes + no review cycle → block: run /simplify."""
        import teammate_stop_gate

        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

    def test_simplify_done_blocks_quality(self):
        """simplify done but not quality → block: run /xp-quality-review."""
        import teammate_stop_gate

        self._set_review_flags(simplify_done=True)
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_quality_done_blocks_security(self):
        """simplify + quality done but not security → block: run /security-review."""
        import teammate_stop_gate

        self._set_review_flags(simplify_done=True, quality_review_done=True)
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        self.assertIsNotNone(result)
        self.assertIn("/security-review", result)

    def test_full_review_blocks_commit(self):
        """Full review cycle done but uncommitted → block: commit."""
        import teammate_stop_gate

        self._set_review_flags(
            simplify_done=True,
            quality_review_done=True,
            security_review_done=True,
        )
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        self.assertIsNotNone(result)
        self.assertIn("commit", result.lower())

    def test_worktree_cwd_detected_as_teammate(self):
        """Worktree cwd without agent_type is detected as teammate."""
        import teammate_stop_gate

        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-abc12345",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

    def test_worktree_cwd_resolves_agent_id(self):
        """Worktree cwd resolves agent_id from worktree directory name."""
        import markers
        import teammate_stop_gate

        markers.set_review_flag(
            self.smm_dir, "worktree-story-abc12345", "simplify_done"
        )
        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-abc12345",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_worktree_cwd_no_marker_blocks_simplify(self):
        """Worktree cwd with no marker file blocks for simplify."""
        import teammate_stop_gate

        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-ffffffff",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

    def test_cli_teammate_worktree_detected(self):
        """CLI teammate worktree path (teammate-*) is detected."""
        import teammate_stop_gate

        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-001",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

    def test_cli_teammate_resolves_agent_id_for_markers(self):
        """CLI teammate uses resolve_agent_id for marker scoping."""
        import markers
        import teammate_stop_gate

        markers.set_review_flag(self.smm_dir, "worktree-story-001", "simplify_done")
        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-001",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

    def test_no_smm_dir_graceful(self):
        """Missing SMM dir exits cleanly."""
        import teammate_stop_gate

        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=Path("/nonexistent/smm"),
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
