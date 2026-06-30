#!/usr/bin/env python3
"""Pins kickoff Step 0: reads the branching stage, conditionally invokes
/xp-stage-migration when stage < 2. The migrate/continue/dismiss body
lives in the xp-stage-migration skill — kickoff carries a slim pointer.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _kickoff_skill import _SKILL_MD, slice_step


class TestKickoffStep0StageMigration(unittest.TestCase):
    """Kickoff Step 0 carries the slim stage-migration delegation."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()
        cls.step = slice_step(cls.text, "## Step 0")

    def test_step_0_exists(self):
        self.assertIn("## Step 0", self.text)
        self.assertTrue(self.step, "Step 0 region is empty")

    def test_step_0_reads_branching_stage(self):
        # The branching.py stage snippet must remain documented for the
        # conditional re-read on stage-mutating paths (system-context /
        # migration), even though the default source is now the preload marker.
        self.assertIn("branching.py", self.step)
        self.assertIn("stage", self.step.lower())

    def test_step_0_reads_stage_from_preload_marker(self):
        # Default source for the stage is the preload's `### STAGE=N` marker —
        # the redundant python callback only survives on the re-read paths.
        # Pin both the marker token AND the "default source" relationship: a
        # prose revert to "always read via branching.py" that left a stray
        # `### STAGE` mention would still flunk the relationship assertion.
        self.assertIn("### STAGE", self.step)
        self.assertIn("default source", self.step.lower())

    def test_step_0_documents_missing_marker_python_fallback(self):
        # No marker (fresh project before /xp-system-context, or a preload that
        # could not compute the stage) must explicitly route to the Python read,
        # not leave the LLM with an undefined STAGE that reads as < 2.
        self.assertIn("no `### STAGE` marker", self.step)

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
        step_3 = slice_step(self.text, "## Step 3")
        self.assertNotIn("/xp-system-context", step_3)


if __name__ == "__main__":
    unittest.main()
