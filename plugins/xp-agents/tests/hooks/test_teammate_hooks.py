#!/usr/bin/env python3
"""Tests for teammate_idle.py and task_completed.py hooks (M13)."""

import sys
import unittest
from pathlib import Path

import review_records

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _HookTestCase,
    _make_task_completed_input,
    _make_teammate_idle_input,
    make_event,
)
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS

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
                    EVENT_TYPE_CONCERN,
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        result = teammate_idle.run(_make_teammate_idle_input(), smm_dir=self.smm_dir)
        assert result is not None
        self.assertIn("failing", result.lower())

    def test_allows_on_passing_tests(self):
        import teammate_idle

        self._write_events(
            [
                make_event(
                    EVENT_TYPE_STATUS,
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
                    EVENT_TYPE_CONCERN,
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
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
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
                    EVENT_TYPE_CONCERN,
                    content="Test failures detected: 2 failed (pytest)",
                    severity="high",
                ),
            ]
        )
        result = task_completed.run(_make_task_completed_input(), smm_dir=self.smm_dir)
        assert result is not None
        self.assertIn("failing", result.lower())

    def test_allows_on_passing_tests(self):
        import task_completed

        self._write_events(
            [
                make_event(
                    EVENT_TYPE_STATUS,
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
                    EVENT_TYPE_CONCERN,
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
            EVENT_TYPE_CONCERN,
            content="Test failures detected: 2 failed (pytest)",
            severity="high",
        )
        resolution = make_event(
            EVENT_TYPE_STATUS,
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

        data = review_records.read_review_flags(self.smm_dir, "worktree-story-1")
        data.update(flags)
        review_records.write_review_flags(self.smm_dir, "worktree-story-1", data)

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

    def test_uncommitted_no_review_blocks_quality(self):
        """Uncommitted changes + no review cycle → block: run /xp-quality-review.

        Per-increment review is /xp-quality-review only (xp-code-reviewer
        self-finds correctness); /code-review no longer gates a stop."""
        import teammate_stop_gate

        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert result is not None
        self.assertIn("/xp-quality-review", result)
        self.assertNotIn("/code-review", result)

    def test_simplify_done_alone_still_blocks_quality(self):
        """simplify_done alone no longer satisfies the gate → still block
        for /xp-quality-review."""
        import teammate_stop_gate

        self._set_review_flags(simplify_done=True)
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert result is not None
        self.assertIn("/xp-quality-review", result)

    def test_full_review_blocks_commit(self):
        """quality_review_done set but uncommitted → block: commit."""
        import teammate_stop_gate

        self._set_review_flags(quality_review_done=True)
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert result is not None
        self.assertEqual(
            result, "Review cycle complete. Commit your changes before stopping."
        )

    def test_worktree_cwd_detected_as_teammate(self):
        """Worktree cwd without agent_type is detected as teammate."""
        import teammate_stop_gate

        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-abc12345",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertIn("/xp-quality-review", result)

    def test_worktree_cwd_resolves_agent_id(self):
        """Worktree cwd resolves agent_id from worktree directory name.

        quality_review_done set under the worktree id → the gate reads that
        marker and advances to the commit message, proving id resolution."""
        import teammate_stop_gate

        review_records.set_review_flag(
            self.smm_dir, "worktree-story-abc12345", "quality_review_done"
        )
        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-abc12345",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertEqual(
            result, "Review cycle complete. Commit your changes before stopping."
        )

    def test_worktree_cwd_no_marker_blocks_quality(self):
        """Worktree cwd with no marker file blocks for /xp-quality-review."""
        import teammate_stop_gate

        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-ffffffff",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertIn("/xp-quality-review", result)

    def test_cli_teammate_worktree_detected(self):
        """CLI teammate worktree path (teammate-*) is detected."""
        import teammate_stop_gate

        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-001",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertIn("/xp-quality-review", result)

    def test_cli_teammate_resolves_agent_id_for_markers(self):
        """CLI teammate uses resolve_agent_id for marker scoping."""
        import teammate_stop_gate

        review_records.set_review_flag(
            self.smm_dir, "worktree-story-001", "quality_review_done"
        )
        inp = {
            "session_id": "t",
            "cwd": "/proj/.claude/worktrees/worktree-story-001",
        }
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertEqual(
            result, "Review cycle complete. Commit your changes before stopping."
        )

    def test_no_smm_dir_graceful(self):
        """Missing SMM dir exits cleanly."""
        import teammate_stop_gate

        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=Path("/nonexistent/smm"),
        )
        self.assertIsNone(result)

    def test_story_cadence_skips_review_demand(self):
        """Story cadence with uncommitted + no review → commit-only, no review demand.

        Under story (deferred-to-merge) cadence, per-increment review is not
        required. The gate still demands the changes be committed, but does
        not ask for /xp-quality-review."""
        import markers
        import teammate_stop_gate

        markers.write_review_cadence(self.smm_dir, "story")
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert result is not None
        self.assertNotIn("/xp-quality-review", result)
        self.assertIn("Commit", result)

    def test_commit_cadence_explicit_demands_review(self):
        """Commit cadence with uncommitted + no review → demand /xp-quality-review.

        Pin the commit cadence branch explicitly (not just as the fail-safe
        default) to ensure the cadence read is load-bearing."""
        import markers
        import teammate_stop_gate

        markers.write_review_cadence(self.smm_dir, "commit")
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert result is not None
        self.assertIn("/xp-quality-review", result)

    def test_no_cadence_marker_defaults_to_review_demand(self):
        """No cadence marker (missing/corrupt) defaults to careful commit cadence.

        The fail-safe default is commit cadence. Without an explicit marker,
        the gate demands /xp-quality-review — load-bearing behavior."""
        import teammate_stop_gate

        # Don't write any cadence marker — test the fail-safe default
        result = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert result is not None
        self.assertIn("/xp-quality-review", result)

    def test_story_cadence_message_differs_from_commit(self):
        """Story vs commit cadence produce different messages (AC-4).

        The message must match the cadence: under commit cadence, only message
        with a completed review is "Review cycle complete. Commit...". Under
        story cadence, the message never mentions review completion."""
        import markers
        import teammate_stop_gate

        # Commit cadence with review done
        markers.write_review_cadence(self.smm_dir, "commit")
        self._set_review_flags(quality_review_done=True)
        commit_msg = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert commit_msg is not None

        # Story cadence with no review done
        markers.write_review_cadence(self.smm_dir, "story")
        # Clear the quality_review_done flag to test story cadence path
        review_records.clear_review_flags(self.smm_dir, "worktree-story-1")
        story_msg = teammate_stop_gate.run(
            _make_teammate_stop_input(),
            smm_dir=self.smm_dir,
            has_uncommitted=True,
        )
        assert story_msg is not None

        # They should differ
        self.assertNotEqual(commit_msg, story_msg)
        # Commit message should mention review cycle
        self.assertIn("Review cycle complete", commit_msg)
        # Story message should not
        self.assertNotIn("Review cycle complete", story_msg)


if __name__ == "__main__":
    unittest.main()
