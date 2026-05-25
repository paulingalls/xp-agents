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

    def test_step_0_bootstraps_system_context_before_stage_gate(self):
        # Step 0 runs /xp-system-context (the only stage-setter) when the
        # preload flags NEEDS_SYSTEM_CONTEXT, BEFORE reading the stage — so a
        # fresh project has a real, analyzer-set stage when the gate fires and
        # an existing system_context.json for the migration's direct write.
        self.assertIn("NEEDS_SYSTEM_CONTEXT", self.step)
        self.assertIn("/xp-system-context", self.step)
        ctx_at = self.step.find("/xp-system-context")
        gate_at = self.step.find("xp-stage-migration")
        self.assertLess(
            ctx_at, gate_at, "system-context must precede the stage-migration gate"
        )

    def test_system_context_invocation_not_duplicated_in_step_3(self):
        # The system-context invocation moved up to Step 0; Step 3 must not
        # re-invoke it (the preload flag is stale once Step 0 has run it).
        step_3 = _slice_step(self.text, "## Step 3")
        self.assertNotIn("/xp-system-context", step_3)


if __name__ == "__main__":
    unittest.main()
