#!/usr/bin/env python3
"""Tests for PreToolUse:Skill hook — simplify nudge + quality-review probe."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertIsNotNone(result)
        self.assertIn("3 review subagents", result)
        self.assertIn("Courage", result)

    def test_simplify_plugin_prefixed(self):
        """Plugin-prefixed simplify also gets nudge."""
        result = pre_tool_skill.run(_make_skill_input("xp-agents:simplify"))
        self.assertIsNotNone(result)
        self.assertIn("3 review subagents", result)

    def test_unrelated_skills_no_output(self):
        """Skills that are neither simplify nor quality-review get nothing."""
        result = pre_tool_skill.run(_make_skill_input("xp-sprint-start"))
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """xp-* agents skip the nudge."""
        result = pre_tool_skill.run(
            _make_skill_input("simplify", agent_type="xp-retrospective")
        )
        self.assertIsNone(result)


class TestQualityReviewProbe(_HookTestCase):
    """PreToolUse:Skill injects resolves probe before /xp-quality-review."""

    @patch("pre_tool_skill._run_qr_probe")
    def test_qr_gets_probe(self, mock_probe):
        mock_probe.return_value = "Found 1 open concern(s)"
        result = pre_tool_skill.run(_make_skill_input("xp-agents:xp-quality-review"))
        self.assertIsNotNone(result)
        self.assertIn("Found 1 open concern", result)
        mock_probe.assert_called_once()

    @patch("pre_tool_skill._run_qr_probe")
    def test_qr_no_concerns(self, mock_probe):
        mock_probe.return_value = "(no open concerns match changed files)"
        result = pre_tool_skill.run(_make_skill_input("xp-quality-review"))
        self.assertIsNotNone(result)
        self.assertIn("no open concerns", result)

    @patch("pre_tool_skill._run_qr_probe")
    def test_qr_no_changed_files(self, mock_probe):
        mock_probe.return_value = "(no changed files)"
        result = pre_tool_skill.run(_make_skill_input("xp-quality-review"))
        self.assertIsNotNone(result)
        self.assertIn("no changed files", result)

    def test_xp_agent_skips_qr_probe(self):
        result = pre_tool_skill.run(
            _make_skill_input("xp-quality-review", agent_type="xp-code-reviewer")
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
