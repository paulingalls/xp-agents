#!/usr/bin/env python3
"""Tests for xp-housekeeping forked skill: preload and subagent dispatch."""

import json
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

    def test_outputs_smm_dir(self):
        """Preload outputs SMM_DIR path."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_outputs_curation_input_path(self):
        """Preload outputs CURATION_INPUT path."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CURATION_INPUT=", result.stdout)

    def test_curation_input_file_created(self):
        """.curation-input.json exists after preload runs."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        curation_file = self.smm_dir / ".curation-input.json"
        self.assertTrue(
            curation_file.exists(),
            f"Expected {curation_file} to exist after preload",
        )

    def test_curation_input_has_expected_keys(self):
        """Curation JSON contains the structured data keys."""
        self._run_preload(_PRELOAD_SCRIPT)
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

    def test_no_xp_values_in_preload(self):
        """Preload no longer includes XP values — injected via SubagentStart."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("XP Values", result.stdout)

    def test_graceful_without_events(self):
        """Empty events.jsonl — preload still succeeds."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)


# ===========================================================================
# SubagentStart dispatch test
# ===========================================================================


class TestSubagentStartHousekeeper(_HookTestCase):
    """xp-housekeeper gets XP values from SubagentStart."""

    def test_xp_housekeeper_gets_values(self):
        """SubagentStart injects XP values for xp-housekeeper."""
        import subagent_start

        result = subagent_start.run(
            {"agent_type": "xp-housekeeper"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)


# ===========================================================================
# Agent prompt content validation (M2: item-level API migration)
# ===========================================================================

_AGENT_PROMPT = Path(__file__).parent.parent.parent / "agents" / "xp-housekeeper.md"


_SKILL_MD = (
    Path(__file__).parent.parent.parent / "skills" / "xp-housekeeping" / "SKILL.md"
)


class TestHousekeepingSkillAllowedTools(unittest.TestCase):
    """M2: Skill allowed-tools include item-level CLI patterns."""

    @classmethod
    def setUpClass(cls):
        cls.skill_text = _SKILL_MD.read_text(encoding="utf-8")

    def test_allows_echo_pipe_smm_cli(self):
        """Allowed tools include echo pipe pattern for add-item/update-item."""
        self.assertIn("Bash(echo *| python3 */smm_cli.py *)", self.skill_text)

    def test_allows_direct_smm_cli(self):
        """Allowed tools include direct pattern for remove-item/complete-curation."""
        self.assertIn("Bash(python3 */smm_cli.py *)", self.skill_text)

    def test_no_full_doc_save_pattern(self):
        """Old full-doc save pattern is removed."""
        self.assertNotIn("Bash(cat *| python3 */smm_cli.py *)", self.skill_text)


class TestHousekeeperPromptItemLevelAPI(unittest.TestCase):
    """M2: Agent prompt uses item-level CLI commands, not full-doc save."""

    @classmethod
    def setUpClass(cls):
        cls.prompt_text = _AGENT_PROMPT.read_text(encoding="utf-8")

    def test_references_add_item(self):
        """Prompt contains add-item CLI command reference."""
        self.assertIn("add-item", self.prompt_text)

    def test_references_update_item(self):
        """Prompt contains update-item CLI command reference."""
        self.assertIn("update-item", self.prompt_text)

    def test_references_remove_item(self):
        """Prompt contains remove-item CLI command reference."""
        self.assertIn("remove-item", self.prompt_text)

    def test_references_complete_curation(self):
        """Prompt contains complete-curation CLI command reference."""
        self.assertIn("complete-curation", self.prompt_text)

    def test_no_full_doc_save_command(self):
        """Prompt does not instruct piping full JSON to smm_cli.py save."""
        self.assertNotIn("smm_cli.py save", self.prompt_text)

    def test_no_full_doc_json_assembly(self):
        """Prompt does not instruct assembling a full JSON document with all pillars."""
        self.assertNotIn('"intent": [', self.prompt_text)
        self.assertNotIn('"constraints": [', self.prompt_text)
        self.assertNotIn('"risks": [', self.prompt_text)
        self.assertNotIn('"wisdom": [', self.prompt_text)

    def test_no_uuid_generation_instructions(self):
        """Prompt does not tell agent to generate or preserve UUIDs."""
        self.assertNotIn("preserve-existing-or-new-uuid4", self.prompt_text)
        self.assertNotIn("emit new UUIDs", self.prompt_text)


if __name__ == "__main__":
    unittest.main()
