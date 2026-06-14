#!/usr/bin/env python3
"""Tests for pre_tool_plan_mode.py: the EnterPlanMode schedule gate.

Blocks entering plan mode in the schedule trigger window (scheduled stories
exist, none in-progress) so /xp-schedule sets the planning scope first. State-
derived: self-clears the instant a frontier is promoted to in-progress.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_plan_mode
from conftest import (
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    SPRINT_SCHEDULED_ONLY,
    _HookTestCase,
)


def _make_plan_mode_input(**overrides) -> dict:
    data = {
        "session_id": "t",
        "tool_name": "EnterPlanMode",
        "tool_input": {},
        "cwd": "/tmp",
        "agent_id": "main",
    }
    data.update(overrides)
    return data


class TestPreToolPlanModeGate(_HookTestCase):
    def test_blocked_in_trigger_state(self):
        """Scheduled stories, none in-progress -> EnterPlanMode blocked."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
        self.assertIn("xp-schedule", str(ctx.exception))

    def test_allowed_when_in_progress(self):
        """A promoted frontier self-clears the gate -> plan entry allowed."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        self.assertIsNone(
            pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
        )

    def test_allowed_no_sprint(self):
        """Free mode / no sprint -> plan entry allowed."""
        self.assertIsNone(
            pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
        )

    def test_allowed_when_no_scheduled(self):
        """Ready-but-not-scheduled stories don't trip the gate."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        self.assertIsNone(
            pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
        )

    def test_xp_agent_exempt(self):
        """xp-* subagents are exempt even in the trigger window."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)
        self.assertIsNone(
            pre_tool_plan_mode.run(
                _make_plan_mode_input(agent_type="xp-agents:xp-housekeeper"),
                smm_dir=self.smm_dir,
            )
        )


if __name__ == "__main__":
    unittest.main()
