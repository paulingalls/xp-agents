#!/usr/bin/env python3
"""Tests for /xp-plan skill: preload and file structure."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _IntegrationTestCase

_SKILL_DIR = Path(__file__).parent.parent.parent / "skills" / "xp-plan"
_PRELOAD_SCRIPT = _SKILL_DIR / "scripts" / "preload.sh"
_SKILL_MD = _SKILL_DIR / "SKILL.md"

_SAMPLE_PLAN = """\
# Execution Plan: Test

## Sources

| Label | Location | Type |
|-------|----------|------|
| Design | docs/design.md | repo |

## Change Overview
Test change.

## Milestones

### Milestone 1: First [planned]
- **Goal:** Do the first thing
- **Definition of Done:** Tests pass

### Milestone 2: Second [in-progress]
- **Goal:** Do the second thing
- **Definition of Done:** Integration works

### Milestone 3: Third [delivered: sprint-001]
- **Goal:** Already done
- **Definition of Done:** Shipped
"""


class TestExecutionPlanFileStructure(unittest.TestCase):
    """Verify skill files exist with correct structure."""

    def test_skill_md_exists(self):
        self.assertTrue(_SKILL_MD.exists(), f"Missing {_SKILL_MD}")

    def test_skill_md_is_inline(self):
        """SKILL.md should NOT have context: fork (inline skill)."""
        content = _SKILL_MD.read_text()
        self.assertNotIn("context: fork", content)

    def test_skill_md_has_frontmatter(self):
        content = _SKILL_MD.read_text()
        self.assertTrue(content.startswith("---"))

    def test_skill_md_name(self):
        content = _SKILL_MD.read_text()
        self.assertIn("name: xp-plan", content)

    def test_skill_md_allowed_tools(self):
        """Must include Read, AskUserQuestion, and save script."""
        content = _SKILL_MD.read_text()
        self.assertIn("Read", content)
        self.assertIn("AskUserQuestion", content)
        self.assertIn("save_planning_doc.py", content)

    def test_skill_md_references_system_context(self):
        """Must mention /xp-system-context for when it's missing."""
        content = _SKILL_MD.read_text()
        self.assertIn("xp-system-context", content)

    def test_preload_script_exists(self):
        self.assertTrue(_PRELOAD_SCRIPT.exists(), f"Missing {_PRELOAD_SCRIPT}")


class TestExecutionPlanPreload(_IntegrationTestCase):
    """Preload detects create vs update mode and counts milestones."""

    def test_outputs_smm_dir(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_create_mode_when_missing(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No execution plan found", result.stdout)

    def test_update_mode_when_exists(self):
        (self.smm_dir / "execution_plan.md").write_text(_SAMPLE_PLAN)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EXECUTION_PLAN=", result.stdout)
        self.assertIn("Existing Execution Plan", result.stdout)

    def test_counts_milestones(self):
        (self.smm_dir / "execution_plan.md").write_text(_SAMPLE_PLAN)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 milestones planned", result.stdout)
        self.assertIn("1 in-progress", result.stdout)
        self.assertIn("1 delivered", result.stdout)

    def test_symlink_treated_as_missing(self):
        real = self.smm_dir / "real.md"
        real.write_text(_SAMPLE_PLAN)
        (self.smm_dir / "execution_plan.md").symlink_to(real)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No execution plan found", result.stdout)

    def test_reports_system_context_missing(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NEEDS_SYSTEM_CONTEXT=true", result.stdout)

    def test_reports_system_context_present(self):
        (self.smm_dir / "system_context.md").write_text("# Context")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEM_CONTEXT=", result.stdout)
        self.assertNotIn("NEEDS_SYSTEM_CONTEXT", result.stdout)


if __name__ == "__main__":
    unittest.main()
