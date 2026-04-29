#!/usr/bin/env python3
"""Tests for kickoff_gate hook.

Kickoff-done tests migrated to test_subagent.py::TestHousekeepingDone as
part of the PostToolUse:Skill replacement plan — the housekeeping handler
now lives in subagent_stop.py.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase

# ===========================================================================
# kickoff_gate.py tests
# ===========================================================================


class TestKickoffGate(_HookTestCase):
    """Tests for UserPromptSubmit kickoff gate."""

    def test_blocks_when_marker_exists(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").touch()
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")

    def test_allows_session_review_command(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").touch()
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "/xp-kickoff"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_kickoff_clears_marker(self):
        """Marker cleared when /xp-kickoff runs so sub-skills can AskUserQuestion."""
        import kickoff_gate

        marker = self.smm_dir / ".needs-kickoff"
        marker.write_text("startup")
        kickoff_gate.run(
            {"session_id": "test", "prompt": "/xp-kickoff"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(marker.exists())

    def test_kickoff_does_not_set_needs_housekeeping(self):
        """Kickoff gate no longer sets .needs-housekeeping — work-selection
        preload sets it later so the stop gate doesn't block mid-kickoff."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        kickoff_gate.run(
            {"session_id": "test", "prompt": "/xp-kickoff"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".needs-housekeeping").exists())

    def test_kickoff_name_variants_clear_marker(self):
        """Every supported invocation form of xp-kickoff clears the marker.

        Covers bare and marketplace-qualified forms, with and without args.
        """
        import kickoff_gate

        variants = [
            "/xp-kickoff",
            "/xp-kickoff --verbose",
            "/xp-agents:xp-kickoff",
            "/xp-agents:xp-kickoff help",
            "/other-team:xp-kickoff",
        ]
        for prompt in variants:
            with self.subTest(prompt=prompt):
                marker = self.smm_dir / ".needs-kickoff"
                marker.write_text("startup")
                result = kickoff_gate.run(
                    {"session_id": "test", "prompt": prompt},
                    smm_dir=self.smm_dir,
                )
                self.assertIsNone(result)
                self.assertFalse(marker.exists())

    def test_subsequent_prompts_pass_after_kickoff_clears_marker(self):
        """After /xp-kickoff clears the marker, AskUserQuestion prompts pass."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        kickoff_gate.run(
            {"session_id": "test", "prompt": "/xp-kickoff"},
            smm_dir=self.smm_dir,
        )
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "Build a TODO app"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_passes_when_no_marker(self):
        import kickoff_gate

        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").touch()
        result = kickoff_gate.run(
            {
                "session_id": "test",
                "prompt": "work",
                "agent_type": "xp-nav",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_worktree_teammate_skips_via_cwd(self):
        """Teammate detected by CWD path skips kickoff gate."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result = kickoff_gate.run(
            {
                "session_id": "test",
                "prompt": "work",
                "cwd": "/project/.claude/worktrees/worktree-story-step-1/src",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_non_teammate_worktree_not_skipped(self):
        """Non-teammate worktrees (e.g. user EnterWorktree) go through the gate."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result = kickoff_gate.run(
            {
                "session_id": "test",
                "prompt": "work",
                "cwd": "/project/.claude/worktrees/explore-abc/src",
            },
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")

    def test_worktree_teammate_skips_via_env_var(self):
        """Teammate detected by XP_TEAMMATE_NAME env var skips kickoff gate."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        with patch.dict(os.environ, {"XP_TEAMMATE_NAME": "worktree-story-step-1"}):
            result = kickoff_gate.run(
                {
                    "session_id": "test",
                    "prompt": "work",
                    "cwd": "/project/src",
                },
                smm_dir=self.smm_dir,
            )
        self.assertIsNone(result)

    def test_clear_marker_nudges_instead_of_blocking(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("clear")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result, "nudge")

    def test_startup_marker_blocks(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["decision"], "block")

    def test_second_prompt_passes_after_block(self):
        """After first block consumes marker, subsequent prompts pass through."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result1 = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result1["decision"], "block")

        result2 = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result2)

    def test_second_prompt_passes_after_nudge(self):
        """After first nudge consumes marker, subsequent prompts pass through."""
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("clear")
        result1 = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result1, "nudge")

        result2 = kickoff_gate.run(
            {"session_id": "test", "prompt": "do some work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result2)

    def test_skips_task_notifications(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        task_prompt = (
            "<task-notification>\n<task-id>abc</task-id>\n</task-notification>"
        )
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": task_prompt},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


# ===========================================================================
# M8a: kickoff_gate sprint marker info tests
# ===========================================================================


class TestKickoffGateSprintInfo(_HookTestCase):
    """M8a: kickoff_gate includes sprint marker info in block message."""

    def test_block_includes_execution_plan_info(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        (self.smm_dir / ".needs-execution-plan").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("xp-plan", result["reason"].lower())

    def test_block_includes_sprint_info(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("sprint", result["reason"].lower())

    def test_block_includes_both(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        (self.smm_dir / ".needs-execution-plan").write_text("startup")
        (self.smm_dir / ".needs-sprint").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertIn("xp-plan", result["reason"].lower())
        self.assertIn("sprint", result["reason"].lower())

    def test_block_no_sprint_markers(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("startup")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertIsInstance(result, dict)
        self.assertNotIn("product", result["reason"].lower())

    def test_nudge_still_works_with_sprint_markers(self):
        import kickoff_gate

        (self.smm_dir / ".needs-kickoff").write_text("clear")
        (self.smm_dir / ".needs-product-spec").write_text("clear")
        (self.smm_dir / ".needs-sprint").write_text("clear")
        result = kickoff_gate.run(
            {"session_id": "test", "prompt": "do work"},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(result, "nudge")


if __name__ == "__main__":
    unittest.main()
