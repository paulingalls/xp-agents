#!/usr/bin/env python3
"""Tests for xp-housekeeping forked skill: preload and subagent dispatch."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from conftest import _HookTestCase, _IntegrationTestCase

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-housekeeping"
    / "scripts"
    / "preload.sh"
)


# ===========================================================================
# Preload integration tests
# ===========================================================================


class TestHousekeepingPreload(_IntegrationTestCase):
    """M2: Forked housekeeping preload creates curation input and outputs paths."""

    def _run_preload(self) -> subprocess.CompletedProcess:
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

    def test_outputs_smm_dir(self):
        """Preload outputs SMM_DIR path."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_outputs_curation_input_path(self):
        """Preload outputs CURATION_INPUT path."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CURATION_INPUT=", result.stdout)

    def test_curation_input_file_created(self):
        """.curation-input.json exists after preload runs."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        curation_file = self.smm_dir / ".curation-input.json"
        self.assertTrue(
            curation_file.exists(),
            f"Expected {curation_file} to exist after preload",
        )

    def test_curation_input_has_expected_keys(self):
        """Curation JSON contains the structured data keys."""
        self._run_preload()
        curation_file = self.smm_dir / ".curation-input.json"
        if not curation_file.exists():
            self.skipTest(".curation-input.json not created")
        data = json.loads(curation_file.read_text())
        for key in (
            "current_smm",
            "new_since_last_curation",
            "retro_history",
            "aging",
            "health",
        ):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_outputs_xp_values(self):
        """Preload includes XP values (not process guide) for curation."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("XP Values", result.stdout)
        self.assertNotIn("EnterPlanMode", result.stdout)

    def test_graceful_without_events(self):
        """Empty events.jsonl — preload still succeeds."""
        result = self._run_preload()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)


# ===========================================================================
# SubagentStart dispatch test
# ===========================================================================


class TestSubagentStartSkipsHousekeeper(_HookTestCase):
    """M2: xp-housekeeper agent type returns None from SubagentStart."""

    def test_xp_housekeeper_returns_none(self):
        """SubagentStart skips xp-housekeeper via xp-* guard."""
        import subagent_start

        result = subagent_start.run(
            {"agent_type": "xp-housekeeper"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
