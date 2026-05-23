#!/usr/bin/env python3
"""Integration tests for the /xp-free-close skill.

Mirrors test_sprint_close.py for TARGET_BRANCH resolution — preload
calls branching.py get-target, which returns the recorded plan branch
when execution_plan.json sets one AND that branch exists locally, else
falls back to the primary integration branch. Two cases are pinned:
`test_emits_target_branch_as_primary_when_no_plan` (no plan recorded →
primary) and `test_emits_target_branch_as_plan_when_plan_set` (plan
recorded + local branch present → plan branch). The close-reviewer
agent's `### free` section already exists; this skill's job is to fork
it.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import seed_plan, write_system_context
from _close_fixtures import (
    _ClosePreloadCommonTests,
    _CloseSkillTextCommonTests,
    _Step4SecurityIncludeTests,
)
from conftest import _extract_preload_var, _IntegrationTestCase


class TestFreeClosePreload(_ClosePreloadCommonTests, _IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"

    def test_emits_target_branch_as_primary_when_no_plan(self):
        # No plan branch recorded → get-target falls back to get-primary.
        # Pins the no-plan fallback half of the get-target contract; the
        # plan-branch half is pinned by
        # test_emits_target_branch_as_plan_when_plan_set below.
        write_system_context(self.smm_dir, stage=2)
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        primary = subprocess.run(
            [
                sys.executable,
                str(_PLUGIN_ROOT / "scripts" / "branching.py"),
                "--smm-dir",
                str(self.smm_dir),
                "get-primary",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertNotEqual(primary, "", "branching.py get-primary must resolve")
        self.assertEqual(_extract_preload_var(result.stdout, "TARGET_BRANCH"), primary)

    def test_emits_target_branch_as_plan_when_plan_set(self):
        # When execution_plan.json records a plan branch AND that branch
        # exists locally, TARGET_BRANCH resolves to the plan branch (sprint-
        # close parity). A free branch forked off a plan branch must merge
        # back to the plan branch, never to main.
        write_system_context(self.smm_dir, stage=2)
        seed_plan(self.smm_dir, branch="test/plan-feat")
        subprocess.run(
            ["git", "branch", "test/plan-feat"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        result = self._preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            _extract_preload_var(result.stdout, "TARGET_BRANCH"), "test/plan-feat"
        )


_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "SKILL.md"


class TestFreeCloseSkillText(_CloseSkillTextCommonTests, unittest.TestCase):
    """Free-close SKILL.md guard tests.

    Inherits the nine shared close-skill guards from
    _CloseSkillTextCommonTests. Adds the plan/free-shared
    current==target refusal (sprint-close has its own logic instead).
    """

    _SKILL_MD = _SKILL_MD
    _MODE = "free"


class TestFreeCloseStep4(_Step4SecurityIncludeTests, _IntegrationTestCase):
    """Step 4 (Security Review) wired into xp-free-close."""

    _SKILL_MD = _SKILL_MD
    _MODE = "free"
    _SKILL_NAME = "xp-free-close"


if __name__ == "__main__":
    unittest.main()
