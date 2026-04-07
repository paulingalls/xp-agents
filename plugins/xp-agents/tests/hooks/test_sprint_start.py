#!/usr/bin/env python3
"""Tests for save_sprint.py and sprint start preload."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _IntegrationTestCase

# ===========================================================================
# save_sprint.py — Atomic writer for sprint.md
# ===========================================================================

_SAVE_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-start"
    / "scripts"
    / "save_sprint.py"
)


class TestSaveSprint(_HookTestCase):
    """Tests for the save_sprint.py atomic writer."""

    def _run_save(self, content: str) -> None:
        """Import and call save_sprint.run() directly."""
        if not _SAVE_SCRIPT.is_file():
            self.skipTest("save_sprint.py not yet created")
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_sprint")
        importlib.reload(mod)  # ensure fresh import
        mod.run(content, self.smm_dir)

    def test_writes_sprint_md(self):
        """Creates sprint.md with given content."""
        content = (
            "# Sprint: Build auth system\n\n"
            "- **Sprint ID:** sprint-001\n"
            "- **Started:** 2026-04-01\n\n"
            "## Stories\n\n"
            "### story-001: As a user I can register\n"
            "- **Size:** M\n"
            "- **Status:** ready\n"
        )
        self._run_save(content)
        target = self.smm_dir / "sprint.md"
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), content)

    def test_overwrites_existing(self):
        """Replaces existing sprint.md content."""
        target = self.smm_dir / "sprint.md"
        target.write_text("old sprint content")
        new_content = "# Sprint: Updated\n"
        self._run_save(new_content)
        self.assertEqual(target.read_text(), new_content)

    def test_rejects_symlink(self):
        """Raises OSError when sprint.md is a symlink."""
        target = self.smm_dir / "sprint.md"
        real_file = self.smm_dir / "real.md"
        real_file.write_text("real")
        target.symlink_to(real_file)
        with self.assertRaises(OSError):
            self._run_save("new content")

    def test_content_passthrough(self):
        """Deferred stories and various statuses are preserved verbatim."""
        content = (
            "# Sprint: Build user management\n\n"
            "- **Sprint ID:** sprint-002\n"
            "- **Started:** 2026-04-01\n\n"
            "## Stories\n\n"
            "### story-001: As a user I can register\n"
            "- **Size:** M\n"
            "- **Status:** done\n\n"
            "### story-002: As a user I can login\n"
            "- **Size:** S\n"
            "- **Status:** deferred\n\n"
            "### story-003: As an admin I can list users\n"
            "- **Size:** L\n"
            "- **Status:** ready\n"
        )
        self._run_save(content)
        self.assertEqual((self.smm_dir / "sprint.md").read_text(), content)


# ===========================================================================
# preload.sh — Sprint start preload script
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-start"
    / "scripts"
    / "preload.sh"
)


class TestSprintStartPreload(_IntegrationTestCase):
    """Tests for the sprint start preload script."""

    def _run_preload(self) -> subprocess.CompletedProcess:
        """Run preload.sh as a subprocess."""
        if not _PRELOAD_SCRIPT.is_file():
            self.skipTest("preload.sh not yet created")
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_DATA"] = str(self._plugin_data_dir)
        return subprocess.run(
            ["bash", str(_PRELOAD_SCRIPT)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=env,
        )

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        # Need product_spec.md to avoid early error exit
        (self.smm_dir / "product_spec.md").write_text(
            "# Product Spec\n\n### Auth [planned]\n- Login\n"
        )
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_no_product_spec(self):
        """Outputs error when no product_spec.md exists."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)
        self.assertIn("product_spec", result.stdout.lower())

    def test_preload_no_planned_features(self):
        """Outputs error when product_spec has only delivered features."""
        (self.smm_dir / "product_spec.md").write_text(
            "# Product Spec\n\n### Auth [delivered: sprint-001]\n- Login\n"
        )
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)

    def test_preload_with_planned_features(self):
        """Outputs path and counts, not full spec content."""
        (self.smm_dir / "product_spec.md").write_text(
            "# Product Spec\n\n"
            "### Auth [planned]\n- Login with email\n\n"
            "### Search [planned]\n- Full-text search\n"
        )
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("PRODUCT_SPEC=", result.stdout)
        self.assertIn("2", result.stdout)  # 2 planned features
        # Should NOT contain full spec content — agent reads via Read tool
        self.assertNotIn("Auth [planned]", result.stdout)

    def test_preload_existing_sprint_deferred(self):
        """Shows deferred stories from existing sprint.md."""
        (self.smm_dir / "product_spec.md").write_text(
            "# Product Spec\n\n### Auth [planned]\n- Login\n"
        )
        (self.smm_dir / "sprint.md").write_text(
            "# Sprint: Previous\n\n## Stories\n\n"
            "### story-001: As a user I can register\n"
            "- **Status:** done\n\n"
            "### story-002: As a user I can login\n"
            "- **Status:** deferred\n"
        )
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("Deferred", result.stdout)

    def test_preload_sprint_count(self):
        """Outputs correct NEXT_SPRINT_ID based on existing sprint events."""
        (self.smm_dir / "product_spec.md").write_text(
            "# Product Spec\n\n### Auth [planned]\n- Login\n"
        )
        # Seed two sprint-start events
        events = [
            json.dumps(
                {
                    "id": "e1",
                    "ts": "2026-03-01T00:00:00Z",
                    "type": "sprint",
                    "agent_id": "xp-sprint-start",
                    "content": "Sprint 1",
                    "metadata": {"sprint_id": "sprint-001", "action": "start"},
                    "schema_version": 1,
                }
            ),
            json.dumps(
                {
                    "id": "e2",
                    "ts": "2026-03-15T00:00:00Z",
                    "type": "sprint",
                    "agent_id": "xp-sprint-start",
                    "content": "Sprint 2",
                    "metadata": {"sprint_id": "sprint-002", "action": "start"},
                    "schema_version": 1,
                }
            ),
        ]
        (self.smm_dir / "events.jsonl").write_text("\n".join(events) + "\n")
        result = self._run_preload()
        self.assertEqual(result.returncode, 0)
        self.assertIn("sprint-003", result.stdout)


if __name__ == "__main__":
    unittest.main()
