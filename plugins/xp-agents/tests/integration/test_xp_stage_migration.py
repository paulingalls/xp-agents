#!/usr/bin/env python3
"""Integration tests for xp-stage-migration SKILL.md prose contract.

The Stage 2 floor migration prompt was extracted from xp-kickoff Step 2.4
into its own skill so kickoff doesn't pay the ~430-token tax every session
for a step that fires at most once per project. This file pins the prose
the new skill must carry to preserve the original Step 2.4 behavior.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _branching_fixtures import write_system_context
from conftest import _PLUGIN_ROOT, _IntegrationTestCase

_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-stage-migration" / "SKILL.md"


class TestXpStageMigrationSkill(unittest.TestCase):
    """xp-stage-migration carries the migrate/continue/dismiss contract."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_skill_reads_branching_stage(self):
        self.assertIn("branching.py", self.text)
        self.assertIn("stage", self.text.lower())

    def test_skill_uses_askuser_question(self):
        self.assertIn("AskUserQuestion", self.text)

    def test_skill_offers_migrate_or_continue(self):
        lower = self.text.lower()
        self.assertIn("migrate", lower)
        self.assertIn("continue", lower)

    def test_skill_sets_stage_directly_on_migrate(self):
        # Migrate writes the stage-2 floor directly via edit-branching-field;
        # it does NOT dispatch /xp-sprint-start (that skill never sets the
        # stage and needs a plan a fresh project lacks — the bootstrap
        # deadlock this fix removes).
        # `printf '2'` piped into `edit-branching-field stage` is the direct
        # floor-write — distinct from the dismissal's `stage_prompt_dismissed_at`.
        self.assertIn("printf '2'", self.text)
        self.assertIn("edit-branching-field stage\n", self.text)
        self.assertNotIn("/xp-sprint-start", self.text)

    def test_skill_records_dismissal_on_continue(self):
        self.assertIn("stage_prompt_dismissed_at", self.text)
        self.assertIn("edit-branching-field", self.text)

    def test_skill_logs_dismissed_at_when_already_set(self):
        lower = self.text.lower()
        self.assertIn("dismissed", lower)


class TestStageMigrationDirectWriteBehavior(_IntegrationTestCase):
    """The migrate branch's direct stage-2 write breaks the bootstrap deadlock.

    Characterization guard (not red-first — the production mechanism already
    exists): pins that a stage-0 project reaches stage 2 and can create
    branches through a plain `edit-branching-field stage` write, with NO sprint
    or plan — which the old `/xp-sprint-start` dispatch could never achieve.
    """

    def setUp(self):
        super().setUp()
        write_system_context(self.smm_dir, stage=0)

    def _write_stage(self, value: str) -> subprocess.CompletedProcess:
        cli = _PLUGIN_ROOT / "smm" / "system_context_cli.py"
        return subprocess.run(
            [
                "python3",
                str(cli),
                "--smm-dir",
                str(self.smm_dir),
                "edit-branching-field",
                "stage",
            ],
            input=value,
            cwd=self.tmpdir,
            env=self._test_env,
            capture_output=True,
            text=True,
        )

    def test_direct_write_promotes_stage_0_to_2(self):
        import branching

        self.assertEqual(branching.get_branching_stage(self.smm_dir), 0)
        result = self._write_stage("2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(branching.get_branching_stage(self.smm_dir), 2)

    def test_branch_creation_unblocked_after_floor_write(self):
        import branching

        # Deadlock state: below the floor, create returns None (no branch).
        self.assertIsNone(
            branching.create_free_branch(str(self.tmpdir), "probe", self.smm_dir)
        )
        self._write_stage("2")
        # Floor set: the free branch now creates without a sprint or plan.
        self.assertIsNotNone(
            branching.create_free_branch(str(self.tmpdir), "probe", self.smm_dir)
        )


if __name__ == "__main__":
    unittest.main()
