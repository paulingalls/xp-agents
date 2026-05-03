#!/usr/bin/env python3
"""Integration tests for xp-kickoff Step 2.4 (Stage 2 floor migration prompt).

M-7 raises the branching-doctrine floor from Stage 1 to Stage 2. Story-001
auto-promotes Stage 1 -> 2 transparently inside branching.py, so the only
case where stage<2 persists across kickoffs is explicit Stage 0. This file
pins the SKILL.md prose contract for the migration prompt that Step 2.4
shows in that case.
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


class TestKickoffStageFloorPrompt(unittest.TestCase):
    """SKILL.md prose pins the new Step 2.4 stage-floor migration contract."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()
        cls.step = _slice_step(cls.text, "## Step 2.4")

    def test_step_24_exists(self):
        self.assertIn("## Step 2.4", self.text)
        self.assertTrue(self.step, "Step 2.4 region is empty")

    def test_step_24_describes_stage_floor(self):
        lower = self.step.lower()
        self.assertIn("stage 2", lower)
        self.assertIn("floor", lower)

    def test_step_24_references_sprint_start(self):
        self.assertIn("/xp-sprint-start", self.step)

    def test_step_24_reads_stage(self):
        self.assertIn("branching.py", self.step)
        self.assertIn("stage", self.step.lower())

    def test_step_24_uses_askuser_question(self):
        self.assertIn("AskUserQuestion", self.step)

    def test_step_24_skips_when_stage_ge_2(self):
        lower = self.step.lower()
        self.assertIn("skip this step", lower)
        self.assertTrue(
            ">= 2" in self.step or "≥ 2" in self.step or ">=2" in self.step,
            "Step 2.4 must describe a skip-when-stage-≥2 condition",
        )

    def test_step_24_lives_between_step_2_and_step_25(self):
        # Migration prompt must fire before any branch-creation work in 2.5+.
        idx_step_2 = self.text.find("## Step 2: Session mode")
        idx_step_24 = self.text.find("## Step 2.4")
        idx_step_25 = self.text.find("## Step 2.5")
        self.assertGreater(idx_step_2, 0)
        self.assertGreater(idx_step_24, idx_step_2)
        self.assertGreater(idx_step_25, idx_step_24)


if __name__ == "__main__":
    unittest.main()
