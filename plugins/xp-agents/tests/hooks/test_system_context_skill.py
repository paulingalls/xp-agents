#!/usr/bin/env python3
"""Tests for xp-system-context forked skill: preload and file structure."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from conftest import _IntegrationTestCase

_SKILL_DIR = Path(__file__).parent.parent.parent / "skills" / "xp-system-context"
_PRELOAD_SCRIPT = _SKILL_DIR / "scripts" / "preload.sh"
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_AGENT_MD = Path(__file__).parent.parent.parent / "agents" / "xp-system-context.md"


# ===========================================================================
# File structure tests
# ===========================================================================


class TestSystemContextFileStructure(unittest.TestCase):
    """Verify skill and agent files exist with correct structure."""

    def test_skill_md_exists(self):
        """SKILL.md exists for xp-system-context."""
        self.assertTrue(_SKILL_MD.exists(), f"Missing {_SKILL_MD}")

    def test_skill_md_is_forked(self):
        """SKILL.md declares context: fork."""
        content = _SKILL_MD.read_text()
        self.assertIn("context: fork", content)

    def test_skill_md_references_agent(self):
        """SKILL.md references xp-system-context agent."""
        content = _SKILL_MD.read_text()
        self.assertIn("xp-system-context", content)

    def test_agent_md_exists(self):
        """Agent definition exists."""
        self.assertTrue(_AGENT_MD.exists(), f"Missing {_AGENT_MD}")

    def test_agent_md_has_frontmatter(self):
        """Agent definition has YAML frontmatter."""
        content = _AGENT_MD.read_text()
        self.assertTrue(content.startswith("---"))

    def test_preload_script_exists(self):
        """Preload script exists."""
        self.assertTrue(_PRELOAD_SCRIPT.exists(), f"Missing {_PRELOAD_SCRIPT}")


# ===========================================================================
# Preload integration tests
# ===========================================================================


class TestSystemContextPreload(_IntegrationTestCase):
    """Preload detects create vs update mode."""

    def test_outputs_smm_dir(self):
        """Preload outputs SMM_DIR path."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_create_mode_when_missing(self):
        """Reports create mode when system_context.md doesn't exist."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MODE=create", result.stdout)

    def test_update_mode_when_exists(self):
        """Reports update mode when system_context.md exists."""
        (self.smm_dir / "system_context.md").write_text("# System Context: Test")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MODE=update", result.stdout)

    def test_symlink_treated_as_missing(self):
        """Symlink system_context.md is treated as missing (create mode)."""
        real = self.smm_dir / "real.md"
        real.write_text("real")
        (self.smm_dir / "system_context.md").symlink_to(real)

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("MODE=create", result.stdout)

    def test_existing_path_output(self):
        """When file exists, preload outputs its path."""
        ctx = self.smm_dir / "system_context.md"
        ctx.write_text("# System Context: Test")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEM_CONTEXT=", result.stdout)


if __name__ == "__main__":
    unittest.main()
