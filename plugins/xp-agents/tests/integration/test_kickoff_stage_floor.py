#!/usr/bin/env python3
"""Integration tests for xp-kickoff Step 2.4 (Stage 2 floor migration prompt).

Step 2.4 originally inlined the migrate/continue/dismiss flow (~430 tokens
injected at every kickoff). The body was extracted into the xp-stage-migration
skill so kickoff only carries a slim conditional pointer. These tests pin the
slim contract: kickoff must conditionally invoke /xp-stage-migration and
preserve the >= 2 skip + dismissal-already-set short-circuit, but the actual
prompt prose now lives in test_xp_stage_migration.
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
    """Kickoff Step 2.4 carries the slim delegation contract."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()
        cls.step = _slice_step(cls.text, "## Step 2.4")

    def test_step_24_exists(self):
        self.assertIn("## Step 2.4", self.text)
        self.assertTrue(self.step, "Step 2.4 region is empty")

    def test_step_24_reads_branching_stage(self):
        self.assertIn("branching.py", self.step)
        self.assertIn("stage", self.step.lower())

    def test_step_24_skips_when_stage_ge_2(self):
        self.assertTrue(
            ">= 2" in self.step or "≥ 2" in self.step or ">=2" in self.step,
            "Step 2.4 must describe a skip-when-stage-≥2 condition",
        )

    def test_step_24_delegates_to_stage_migration_skill(self):
        self.assertIn("xp-stage-migration", self.step)

    def test_step_24_lives_between_step_2_and_step_25(self):
        idx_step_2 = self.text.find("## Step 2: Session mode")
        idx_step_24 = self.text.find("## Step 2.4")
        idx_step_25 = self.text.find("## Step 2.5")
        self.assertGreater(idx_step_2, 0)
        self.assertGreater(idx_step_24, idx_step_2)
        self.assertGreater(idx_step_25, idx_step_24)

    def test_step_24_is_slim(self):
        """The whole point of the extraction: kickoff Step 2.4 should be short."""
        line_count = len(self.step.splitlines())
        self.assertLess(
            line_count,
            15,
            f"Step 2.4 is {line_count} lines — extraction goal is < 15 "
            "(was 33 inline before xp-stage-migration extraction)",
        )

    def test_step_24_runs_regardless_of_session_mode(self):
        """Step 2 says 'free session: jump directly to step 5' — Step 2.4
        must explicitly override that, otherwise free-session users skip the
        Stage 2 floor prompt entirely (regression caught at commit 89d8727a).
        """
        lower = self.step.lower()
        self.assertTrue(
            "regardless of" in lower or "always" in lower,
            "Step 2.4 must declare it runs regardless of session mode "
            "(free-session users would otherwise skip per Step 2's jump-to-5)",
        )


if __name__ == "__main__":
    unittest.main()
