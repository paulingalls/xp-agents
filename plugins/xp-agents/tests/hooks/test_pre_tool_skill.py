#!/usr/bin/env python3
"""Tests for PreToolUse:Skill hook — code-review nudge."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import pre_tool_skill
from conftest import _HookTestCase, _make_skill_input


class TestCodeReviewNudge(_HookTestCase):
    """PreToolUse:Skill injects courage nudge before /code-review."""

    def test_code_review_gets_courage_nudge(self):
        """When /code-review runs, inject courage + identify-only reminder."""
        result = pre_tool_skill.run(_make_skill_input("code-review"))
        result = self._assert_not_none(result)
        self.assertIn("Courage", result)
        # /code-review is identify-only now; the fix happens in quality-review.
        self.assertIn("/xp-quality-review", result)
        # The old "code reuse agent" no longer exists — don't resurrect it.
        self.assertNotIn("code reuse agent", result)

    def test_code_review_plugin_prefixed(self):
        """Prefixed code-review also gets nudge."""
        result = pre_tool_skill.run(_make_skill_input("xp-agents:code-review"))
        result = self._assert_not_none(result)
        self.assertIn("Courage", result)

    def test_unrelated_skills_no_output(self):
        """Skills that are not code-review get nothing."""
        result = pre_tool_skill.run(_make_skill_input("xp-sprint-start"))
        self.assertIsNone(result)

    def test_xp_agent_skips(self):
        """xp-* agents skip the nudge."""
        result = pre_tool_skill.run(
            _make_skill_input("code-review", agent_type="xp-retrospective")
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
