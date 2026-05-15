#!/usr/bin/env python3
"""Tests for PreToolUse:Skill hook — simplify nudge."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import pre_tool_skill
from conftest import _HookTestCase, _make_skill_input


class TestSimplifyNudge(_HookTestCase):
    """PreToolUse:Skill injects courage nudge before /simplify."""

    def test_simplify_gets_courage_nudge(self):
        """When /simplify runs, inject courage + subagent reminder."""
        result = pre_tool_skill.run(_make_skill_input("simplify"))
        result = self._assert_not_none(result)
        self.assertIn("3 review subagents", result)
        self.assertIn("Courage", result)

    def test_simplify_plugin_prefixed(self):
        """Plugin-prefixed simplify also gets nudge."""
        result = pre_tool_skill.run(_make_skill_input("xp-agents:simplify"))
        result = self._assert_not_none(result)
        self.assertIn("3 review subagents", result)

    def test_unrelated_skills_no_output(self):
        """Skills that are not simplify get nothing."""
        result = pre_tool_skill.run(_make_skill_input("xp-sprint-start"))
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """xp-* agents skip the nudge."""
        result = pre_tool_skill.run(
            _make_skill_input("simplify", agent_type="xp-retrospective")
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
