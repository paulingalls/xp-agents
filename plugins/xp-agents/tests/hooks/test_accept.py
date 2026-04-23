#!/usr/bin/env python3
"""Tests for the accept preload script.

Stop-gate tests migrated to test_sprint_stop_gate.py.
Accept-done behavior migrated to test_sprint_start.py (save_sprint.py
now handles .accept clearing and iteration_complete recording as part
of the PostToolUse:Skill replacement plan).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_IN_PROGRESS,
    SPRINT_READY_ONLY,
    _IntegrationTestCase,
)

# ===========================================================================
# preload.sh — Accept preload script
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-accept"
    / "scripts"
    / "preload.sh"
)


class TestAcceptPreload(_IntegrationTestCase):
    """M16: preload outputs path, not full sprint content."""

    def test_preload_no_sprint(self):
        """Outputs ERROR when no sprint.json exists."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)

    def test_preload_no_in_progress(self):
        """Outputs NO_IN_PROGRESS when no in-progress stories."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_READY_ONLY)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("NO_IN_PROGRESS", result.stdout)

    def test_preload_outputs_path_not_content(self):
        """Outputs SPRINT_FILE path, not full sprint content."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SPRINT_FILE=", result.stdout)
        # Should NOT contain full sprint content
        self.assertNotIn("**Status:** in-progress", result.stdout)

    def test_preload_shows_in_progress_count(self):
        """Outputs count of in-progress stories."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("in-progress", result.stdout.lower())

    def test_preload_clears_accept_marker(self):
        """Preload clears .accept marker so update-story done is unblocked."""
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(
            (self.smm_dir / ".accept").exists(),
            ".accept marker should be cleared by preload",
        )


class TestAcceptPreloadTypes(_IntegrationTestCase):
    """Preload surfaces acceptance_execution type per in-progress story."""

    def _sprint_with_ae(self, ae_type: str) -> str:
        from conftest import _s, _sprint_json

        story = _s(
            "story-001",
            "Test story",
            "in-progress",
            acceptance_execution={"type": ae_type, "command": "test cmd"},
        )
        return _sprint_json([story])

    def test_preload_shows_acceptance_type(self):
        (self.smm_dir / "sprint.json").write_text(self._sprint_with_ae("pytest"))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("story-001: pytest", result.stdout)

    def test_preload_defaults_to_manual(self):
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("story-001: manual", result.stdout)


if __name__ == "__main__":
    unittest.main()
