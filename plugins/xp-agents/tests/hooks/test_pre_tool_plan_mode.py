#!/usr/bin/env python3
"""Tests for pre_tool_plan_mode.py: the EnterPlanMode schedule gate.

Blocks entering plan mode in the schedule trigger window (scheduled stories
exist, none in-progress) so /xp-schedule sets the planning scope first. State-
derived: self-clears the instant a frontier is promoted to in-progress.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

_STORY_BRANCH = "paulingalls/story-001-schedule-gate"
_FREE_BRANCH = "paulingalls/free-2026-07-13-scratch"


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


class TestPreToolPlanModeFreeBranchExemption(_HookTestCase):
    """The gate's second door carries the same free-branch exemption as the first.

    Both doors run the same schedule gate, and the e2e asserts they block
    together — so they are one mechanism, and exempting only the Write door would
    leave a free-branch session that can write but cannot plan. That is worse than
    either misfire alone: the escape hatch would be half-open.

    Fails closed exactly as the write door does: a git failure reports "" and a
    detached HEAD reports "HEAD", neither of which is a free branch.
    """

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text(SPRINT_SCHEDULED_ONLY)

    def test_free_branch_plan_mode_entry_is_exempt(self):
        """On a free branch the sprint is not the planning frame — plan entry goes."""
        with patch.object(
            pre_tool_plan_mode.identity, "get_current_branch", return_value=_FREE_BRANCH
        ):
            self.assertIsNone(
                pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
            )

    def test_story_branch_plan_mode_entry_still_blocks(self):
        """The intent pin: on a story branch the gate still sets the planning
        scope before any plan is drawn."""
        with (
            patch.object(
                pre_tool_plan_mode.identity,
                "get_current_branch",
                return_value=_STORY_BRANCH,
            ),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
        self.assertIn("xp-schedule", str(ctx.exception))


class TestPreToolPlanModeCorruptSprint(_HookTestCase):
    """A bad read is not "no sprint" — this door fails CLOSED too.

    `load_sprint` RAISES on a corrupt/schema-invalid sprint.json. Letting that
    escape is not a block but an ALLOW: the hook dies with a traceback and exits
    1, which PreToolUse treats as a NON-blocking error, so the gate is skipped
    and plan mode opens with every sprint gate blind.

    The sibling Write door has failed closed here for a while. A door that stops
    the write but waves the plan through is exactly the half-open hatch the
    free-branch exemption was added to avoid — same mechanism, same failure
    posture, both doors.
    """

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text("{ this is not json")

    def test_corrupt_sprint_blocks_plan_mode(self):
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
        self.assertIn("cannot be read", str(ctx.exception))

    def test_corrupt_sprint_blocks_plan_mode_even_on_a_free_branch(self):
        """Free-branch is a claim about SCOPE, not about sprint.json being
        readable — it buys nothing when the gates are blind. Mirrors
        TestCorruptSprintKeepsThePredicatesApart on the write door."""
        with (
            patch.object(
                pre_tool_plan_mode.identity,
                "get_current_branch",
                return_value=_FREE_BRANCH,
            ),
            self.assertRaises(_common.BlockedError) as ctx,
        ):
            pre_tool_plan_mode.run(_make_plan_mode_input(), smm_dir=self.smm_dir)
        self.assertIn("cannot be read", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
