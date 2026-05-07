#!/usr/bin/env python3
"""Integration tests for the /xp-free-close skill.

Mirrors test_plan_close.py — six preload fields, TARGET_BRANCH resolves
to the primary integration branch (free-close merges a free branch into
primary, same as plan-close). The close-reviewer agent's `### free`
section already exists; this skill's job is to fork it.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _branching_fixtures import write_system_context
from _close_fixtures import (
    _ClosePreloadCommonTests,
    _CloseSkillTextCommonTests,
    _Step4SecurityIncludeTests,
)
from conftest import _extract_preload_var, _IntegrationTestCase


class TestFreeClosePreload(_ClosePreloadCommonTests, _IntegrationTestCase):
    """Preload outputs the six fields the close skill needs."""

    _PRELOAD = _PLUGIN_ROOT / "skills" / "xp-free-close" / "scripts" / "preload.sh"

    def test_emits_target_branch_as_primary(self):
        # Free-close merges a free branch into primary — use get-primary,
        # not get-target (free branches aren't plan branches and shouldn't
        # be misrouted by recorded plan branch lookup).
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
