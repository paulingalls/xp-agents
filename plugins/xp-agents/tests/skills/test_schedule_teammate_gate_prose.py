#!/usr/bin/env python3
"""Pin: xp-schedule SKILL.md gates Step 2 on teammate-support flag.

story-004. Step 2 ("Choose the mode") must branch on TEAMMATE_ENABLED:
- false → auto-solo silently, skip mode question
- true → existing three-way logic unchanged (count==1, overlapping, ask)

Solo handoff text (Step 4) must point at /xp-assign, not in-agent.

Prose must be declarative and project-agnostic: no internal marker names.
"""

import unittest
from pathlib import Path

from conftest import _slice, _split_frontmatter_body

_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-schedule" / "SKILL.md"
)


class TestScheduleTeammateGateProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        full_text = _SKILL_PATH.read_text()
        _, cls.body = _split_frontmatter_body(full_text)
        cls.step2 = _slice(cls.body, "## Step 2:", ("## Step 3:",))
        # Step 4 is the last section, so () — to EOF — is the honest bound.
        cls.step4 = _slice(cls.body, "## Step 4:", ())
        cls.frontmatter, _ = _split_frontmatter_body(full_text)

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_step2_gates_on_teammate_enabled(self):
        """AC#1: Step 2 branches on TEAMMATE_ENABLED flag."""
        self.assertIn("TEAMMATE_ENABLED", self.step2)

    def test_step2_auto_solo_when_teammate_disabled(self):
        """AC#1: When TEAMMATE_ENABLED=false, auto-solo without mode question."""
        self.assertIn("TEAMMATE_ENABLED", self.step2)
        self.assertIn("false", self.step2)
        self.assertRegex(
            self.step2,
            r"auto-solo",
            msg="Step 2 must mention auto-solo for disabled teammates",
        )

    def test_step2_keeps_existing_mode_question_when_enabled(self):
        """AC#2: When TEAMMATE_ENABLED=true, existing three-way logic unchanged."""
        self.assertIn("AskUserQuestion", self.step2)
        self.assertRegex(self.step2, r"(?i)count.*1|parallelizable|solo")

    def test_step4_solo_handoff_points_at_xp_assign(self):
        """AC#3: Solo path handoff mentions /xp-assign, not just in-agent."""
        self.assertIn("/xp-assign", self.step4)
        self.assertRegex(
            self.step4,
            r"/xp-assign",
            msg="Step 4 solo handoff must point at /xp-assign",
        )

    def test_prose_uses_no_internal_marker_name(self):
        """Declarative: .teammate-config internal filename must not appear."""
        self.assertNotIn(".teammate-config", self.body)

    def test_prose_uses_generic_vocabulary(self):
        """Project-agnostic: no plugin-internal surface names as rule."""
        # Should use generic terms like "flag", "gate", "decision" not
        # TEAMMATE_CONFIG, .assign-pending, etc.
        internal_terms = ["ASSIGN_PENDING", "REVIEW_CYCLE", "CLOSE_CYCLE"]
        for term in internal_terms:
            self.assertNotIn(
                term,
                self.body,
                msg=f"Internal term {term!r} must not appear in prose",
            )


if __name__ == "__main__":
    unittest.main()
