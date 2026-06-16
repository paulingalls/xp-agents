#!/usr/bin/env python3
"""Integration tests: Tier 1 gate enforcement.

Subprocess-level tests for kickoff_gate, tdd_stop_gate, and sprint_stop_gate.
These are the XP workflow safety nets — if any of them silently fails,
the entire enforcement cascade becomes advisory.

Hook-level tests cover the branching logic in detail. These tests verify
the subprocess path: stdin JSON parsing, stdout decision-block format,
marker file resolution, and recursion-guard behavior.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_CLOSING_WITH_NEXT_SCHEDULED,
    SPRINT_COMPLETE_WITH_ID,
    SPRINT_IN_PROGRESS,
    SPRINT_SCHEDULED_ONLY,
    _IntegrationTestCase,
    failing_tests_concern,
    passing_tests_status,
)

# ---------------------------------------------------------------------------
# kickoff_gate.py — UserPromptSubmit hook
# ---------------------------------------------------------------------------


class TestKickoffGateIntegration(_IntegrationTestCase):
    """Gate blocks non-kickoff prompts until /xp-kickoff runs."""

    def test_startup_marker_blocks_regular_prompt(self):
        (self.smm_dir / ".needs-kickoff").write_text("startup")

        result = self._run_script(
            "kickoff_gate.py",
            {
                "session_id": "it",
                "prompt": "let's work on something",
                "agent_id": "main",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("xp-kickoff", parsed["reason"])
        # Marker consumed on first block — subsequent prompts pass through.
        self.assertFalse((self.smm_dir / ".needs-kickoff").exists())

    def test_kickoff_prompt_consumes_marker(self):
        (self.smm_dir / ".needs-kickoff").write_text("startup")

        result = self._run_script(
            "kickoff_gate.py",
            {
                "session_id": "it",
                "prompt": "/xp-kickoff please",
                "agent_id": "main",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")
        self.assertFalse((self.smm_dir / ".needs-kickoff").exists())

    def test_clear_marker_nudges_not_blocks(self):
        (self.smm_dir / ".needs-kickoff").write_text("clear")

        result = self._run_script(
            "kickoff_gate.py",
            {
                "session_id": "it",
                "prompt": "do work",
                "agent_id": "main",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        # Clear marker emits a hookSpecificOutput nudge, not a block decision.
        parsed = json.loads(result.stdout)
        self.assertNotIn("decision", parsed)
        self.assertIn("hookSpecificOutput", parsed)

    def test_sprint_hint_appended_without_execution_plan(self):
        """needs-sprint alone includes sprint-start hint."""
        (self.smm_dir / ".needs-kickoff").write_text("startup")
        (self.smm_dir / ".needs-sprint").write_text("")

        result = self._run_script(
            "kickoff_gate.py",
            {
                "session_id": "it",
                "prompt": "do work",
                "agent_id": "main",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("/xp-sprint-start", parsed["reason"])
        # Negative: without .needs-product-spec, the product-spec hint is NOT
        # appended. Regression guard against "append every hint unconditionally".
        self.assertNotIn("/xp-product-spec", parsed["reason"])


# ---------------------------------------------------------------------------
# tdd_stop_gate.py — Stop hook
# ---------------------------------------------------------------------------


class TestTddStopGateIntegration(_IntegrationTestCase):
    """Stop is blocked when last test signal is a failure."""

    def test_failing_then_passing_unblocks_flow(self):
        # Red: seed failing test concern.
        concern = failing_tests_concern()
        self._seed_events([concern])

        result = self._run_script(
            "tdd_stop_gate.py",
            {"session_id": "it", "agent_id": "main"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("fix", parsed["reason"].lower())

        # Green: re-seed with the concern followed by a passing status.
        # _seed_events overwrites events.jsonl, so we pass both events in
        # the desired order. find_last_test_signal scans newest-first and
        # returns "pass" as soon as it sees the status event.
        self._seed_events([concern, passing_tests_status()])

        result = self._run_script(
            "tdd_stop_gate.py",
            {"session_id": "it", "agent_id": "main"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_stop_hook_active_allows_failing_tests(self):
        """Recursion guard: stop_hook_active=True bypasses the gate."""
        self._seed_events([failing_tests_concern()])

        result = self._run_script(
            "tdd_stop_gate.py",
            {
                "session_id": "it",
                "agent_id": "main",
                "stop_hook_active": True,
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


# ---------------------------------------------------------------------------
# sprint_stop_gate.py — Stop hook
# ---------------------------------------------------------------------------


class TestSprintStopGateIntegration(_IntegrationTestCase):
    """Sprint lifecycle cascade: accept gate → review gate."""

    def test_accept_cascade_blocks_in_progress_with_marker(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").touch()

        result = self._run_script(
            "sprint_stop_gate.py",
            {"session_id": "it", "agent_id": "main"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("/xp-accept", parsed["reason"])

    def test_review_cascade_blocks_complete_sprint(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)

        result = self._run_script(
            "sprint_stop_gate.py",
            {"session_id": "it", "agent_id": "main"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["decision"], "block")
        self.assertIn("/xp-sprint-review", parsed["reason"])

    def test_asking_user_marker_defers_block(self):
        """Mid-dialogue .asking-user marker defers the sprint cascade."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)
        (self.smm_dir / ".asking-user").write_text("1")

        result = self._run_script(
            "sprint_stop_gate.py",
            {"session_id": "it", "agent_id": "main"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")


# ---------------------------------------------------------------------------
# pre_tool_write.py + pre_tool_plan_mode.py — state-derived schedule gates
# ---------------------------------------------------------------------------


class TestScheduleGateEnforcement(_IntegrationTestCase):
    """Both schedule gates across the pre-promotion window: blocked while
    scheduled stories await a frontier, allowed once one is in-progress.
    """

    def _write_input(self) -> dict:
        return {
            "session_id": "it",
            "tool_name": "Write",
            "tool_input": {"file_path": "src/app.py", "content": "x = 1"},
            "agent_id": "main",
            "cwd": str(self.tmpdir),
        }

    def _plan_mode_input(self) -> dict:
        return {
            "session_id": "it",
            "tool_name": "EnterPlanMode",
            "tool_input": {},
            "agent_id": "main",
            "cwd": str(self.tmpdir),
        }

    def test_blocked_then_allowed_across_promotion(self):
        # Trigger window: scheduled stories, none in-progress.
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)

        write_blocked = self._run_script("pre_tool_write.py", self._write_input())
        self.assertEqual(write_blocked.returncode, 2, write_blocked.stderr)
        self.assertIn("xp-schedule", write_blocked.stderr)

        plan_blocked = self._run_script(
            "pre_tool_plan_mode.py", self._plan_mode_input()
        )
        self.assertEqual(plan_blocked.returncode, 2, plan_blocked.stderr)
        self.assertIn("xp-schedule", plan_blocked.stderr)

        # /xp-schedule promotes a frontier scheduled -> in-progress.
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)

        write_ok = self._run_script("pre_tool_write.py", self._write_input())
        self.assertEqual(write_ok.returncode, 0, write_ok.stderr)

        plan_ok = self._run_script("pre_tool_plan_mode.py", self._plan_mode_input())
        self.assertEqual(plan_ok.returncode, 0, plan_ok.stderr)

    def test_write_allowed_during_close_window(self):
        # /xp-story-close window: story-001 closing, story-002 still scheduled.
        # No story is in-progress, but the close is in motion — the gate must
        # NOT block a review-cycle fix to the closing story by demanding a
        # /xp-schedule that would wrongly promote the next frontier mid-close.
        (self.smm_dir / "sprint.json").write_text(SPRINT_CLOSING_WITH_NEXT_SCHEDULED)

        write_ok = self._run_script("pre_tool_write.py", self._write_input())
        self.assertEqual(write_ok.returncode, 0, write_ok.stderr)

        plan_ok = self._run_script("pre_tool_plan_mode.py", self._plan_mode_input())
        self.assertEqual(plan_ok.returncode, 0, plan_ok.stderr)


if __name__ == "__main__":
    unittest.main()
