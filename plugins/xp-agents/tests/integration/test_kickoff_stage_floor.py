#!/usr/bin/env python3
"""Pins kickoff Step 0: reads the branching stage, conditionally invokes
/xp-stage-migration when stage < 2. The migrate/continue/dismiss body
lives in the xp-stage-migration skill — kickoff carries a slim pointer.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-kickoff" / "SKILL.md"


def _slice_step(text: str, heading: str) -> str:
    """Return one `## Step ...` section, sliced to the next `## Step` header."""
    start = text.find(heading)
    if start < 0:
        return ""
    end = text.find("\n## Step", start + len(heading))
    return text[start:end] if end > 0 else text[start:]


class TestKickoffStep0StageMigration(unittest.TestCase):
    """Kickoff Step 0 carries the slim stage-migration delegation."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()
        cls.step = _slice_step(cls.text, "## Step 0")

    def test_step_0_exists(self):
        self.assertIn("## Step 0", self.text)
        self.assertTrue(self.step, "Step 0 region is empty")

    def test_step_0_reads_branching_stage(self):
        self.assertIn("branching.py", self.step)
        self.assertIn("stage", self.step.lower())

    def test_step_0_skips_migration_when_stage_ge_2(self):
        self.assertTrue(
            "< 2" in self.step or "≥ 2" in self.step or ">= 2" in self.step,
            "Step 0 must describe a stage-2 floor condition",
        )

    def test_step_0_delegates_to_stage_migration_skill(self):
        self.assertIn("xp-stage-migration", self.step)


if __name__ == "__main__":
    unittest.main()
