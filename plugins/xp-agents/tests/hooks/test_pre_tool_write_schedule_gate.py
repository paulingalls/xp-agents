#!/usr/bin/env python3
"""Tests for pre_tool_write.py's schedule gate.

Split from test_pre_tool_write_gates.py, which was at 483 lines and would have
crossed the 500-line cap once the scope-exemption cases landed. The schedule
gate is one mechanism with its own trigger window (scheduled stories exist, no
story in motion) and its own exemption set, so it earns its own file; the plan
review gate, question gate and accept marker stay behind.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_write
from conftest import (
    SPRINT_IN_PROGRESS,
    SPRINT_SCHEDULED_ONLY,
    _HookTestCase,
    _make_write_input,
)


class TestPreToolWriteScheduleGate(_HookTestCase):
    """PreToolUse blocks non-plan/non-SMM writes in the schedule trigger window
    (scheduled stories exist, none in-progress) — forcing /xp-schedule. State-
    derived: self-clears the instant a frontier is promoted to in-progress.
    """

    def test_scheduled_only_blocks_code_write(self):
        """Scheduled stories, none in-progress -> code write blocked."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(
                _make_write_input(session_id="t", cwd="/tmp"),
                smm_dir=self.smm_dir,
            )
        self.assertIn("xp-schedule", str(ctx.exception))

    def test_in_progress_self_clears_gate(self):
        """Once a frontier is in-progress, the gate no longer fires."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-schedule", result)

    def test_no_sprint_does_not_block(self):
        """Free mode / no sprint -> gate never fires."""
        result = pre_tool_write.run(
            _make_write_input(session_id="t", cwd="/tmp"),
            smm_dir=self.smm_dir,
        )
        if result:
            self.assertNotIn("xp-schedule", result)

    def test_plan_file_exempt_in_trigger_state(self):
        """Plan-file writes are exempt even in the trigger window."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan",
            },
        )
        result = pre_tool_write.run(plan_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-schedule", result)

    def test_smm_write_exempt_in_trigger_state(self):
        """Writes targeting the SMM dir are exempt even in the trigger window."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        smm_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": str(self.smm_dir / "scratch.json"),
                "content": "{}",
            },
        )
        result = pre_tool_write.run(smm_input, smm_dir=self.smm_dir)
        if result:
            self.assertNotIn("xp-schedule", result)


if __name__ == "__main__":
    unittest.main()
