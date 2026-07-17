#!/usr/bin/env python3
"""Tests for sprint start preload script.

Split from test_sprint_start.py -- preload.sh integration tests.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc, write_doc
from conftest import _IntegrationTestCase
from event_schema import EVENT_TYPE_SPRINT

_SKILL_MD = (
    Path(__file__).parent.parent.parent / "skills" / "xp-sprint-start" / "SKILL.md"
)

# ===========================================================================
# preload.sh -- Sprint start preload script
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

    def _write_plan(self, milestones=None):
        """Write a valid JSON plan with given milestones."""
        m_base = {
            "goal": "G",
            "done": "D",
            "sources": "",
            "change_zones": [],
            "impact_zones": [],
            "design_details": "",
            "constraints": [],
        }
        if milestones is None:
            milestones = [
                {
                    **m_base,
                    "number": 1,
                    "name": "Auth",
                    "status": "planned",
                    "delivered_sprint": None,
                }
            ]
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(
                {
                    "title": "T",
                    "sources": [],
                    "overview": "",
                    "milestones": milestones,
                }
            )
        )

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        self._write_plan()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_no_execution_plan(self):
        """Outputs error when no execution_plan.json exists."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)
        self.assertIn("execution plan", result.stdout.lower())

    def test_preload_no_planned_milestones(self):
        """Outputs error when plan has only delivered milestones."""
        m_base = {
            "goal": "G",
            "done": "D",
            "sources": "",
            "change_zones": [],
            "impact_zones": [],
            "design_details": "",
            "constraints": [],
        }
        self._write_plan(
            [
                {
                    **m_base,
                    "number": 1,
                    "name": "Auth",
                    "status": "delivered",
                    "delivered_sprint": "sprint-001",
                }
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)

    def test_preload_with_planned_milestones(self):
        """Outputs path and counts."""
        m_base = {
            "goal": "G",
            "done": "D",
            "sources": "",
            "change_zones": [],
            "impact_zones": [],
            "design_details": "",
            "constraints": [],
        }
        self._write_plan(
            [
                {
                    **m_base,
                    "number": 1,
                    "name": "Auth",
                    "status": "planned",
                    "delivered_sprint": None,
                },
                {
                    **m_base,
                    "number": 2,
                    "name": "Search",
                    "status": "planned",
                    "delivered_sprint": None,
                },
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("EXECUTION_PLAN=", result.stdout)
        self.assertIn("planned=2", result.stdout)

    def test_preload_existing_sprint_deferred(self):
        """Shows deferred stories from existing sprint.json."""
        from conftest import _s, _sprint_json

        self._write_plan()
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "Register", "done"),
                    _s("story-002", "Login", "deferred"),
                ],
                goal="Previous",
            )
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Deferred", result.stdout)

    def test_preload_sprint_count(self):
        """Outputs correct NEXT_SPRINT_ID from sprint event count."""
        self._write_plan()
        # Seed two sprint-start events
        events = [
            json.dumps(
                {
                    "id": "e1",
                    "ts": "2026-03-01T00:00:00Z",
                    "type": EVENT_TYPE_SPRINT,
                    "agent_id": "xp-sprint-start",
                    "content": "Sprint 1",
                    "metadata": {
                        "sprint_id": "sprint-001",
                        "action": "start",
                    },
                    "schema_version": 1,
                }
            ),
            json.dumps(
                {
                    "id": "e2",
                    "ts": "2026-03-15T00:00:00Z",
                    "type": EVENT_TYPE_SPRINT,
                    "agent_id": "xp-sprint-start",
                    "content": "Sprint 2",
                    "metadata": {
                        "sprint_id": "sprint-002",
                        "action": "start",
                    },
                    "schema_version": 1,
                }
            ),
        ]
        (self.smm_dir / "events.jsonl").write_text("\n".join(events) + "\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("sprint-003", result.stdout)

    def test_preload_emits_declared_test_command(self):
        """AC1: a declared stack.test_command surfaces as TEST_COMMAND=<cmd>."""
        self._write_plan()
        write_doc(
            self.smm_dir,
            valid_doc(
                stack={"languages": ["Python"], "test_command": "pytest -n auto"}
            ),
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("TEST_COMMAND=pytest -n auto", result.stdout)

    def test_preload_emits_empty_test_command_when_undeclared(self):
        """AC2: no declared test_command -> empty TEST_COMMAND, never invented."""
        self._write_plan()
        write_doc(self.smm_dir, valid_doc(stack={"languages": ["Python"]}))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("TEST_COMMAND=\n", result.stdout)
        self.assertNotIn("pytest", result.stdout)

    def test_preload_emits_framing_safe_test_command(self):
        """AC3: a declared command with framing metacharacters is neutralized
        via emit_var (newline collapsed), not raw-echoed."""
        self._write_plan()
        write_doc(
            self.smm_dir,
            valid_doc(
                stack={
                    "languages": ["Python"],
                    "test_command": "pytest\nTEST_COMMAND=forged",
                }
            ),
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        lines = [
            line
            for line in result.stdout.splitlines()
            if line.startswith("TEST_COMMAND=")
        ]
        self.assertEqual(len(lines), 1, "declared command must not forge extra lines")

    def test_preload_surfaces_non_python_command_unchanged(self):
        """AC4: a non-Python declared command surfaces verbatim, no hardcoded runner."""
        self._write_plan()
        write_doc(
            self.smm_dir,
            valid_doc(stack={"languages": ["Rust"], "test_command": "cargo test"}),
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("TEST_COMMAND=cargo test", result.stdout)
        self.assertNotIn("pytest", result.stdout)

    def test_skill_md_authors_acceptance_from_declared_test_command(self):
        """AC5 (realness): SKILL.md must instruct authoring
        acceptance_execution.command from TEST_COMMAND, and must not
        instruct hardcoding a 'python3 -m pytest' runner. Surfacing the
        variable alone is not sufficient -- last sprint the LLM invented
        a runner despite the field being schema-declared."""
        text = _SKILL_MD.read_text()
        self.assertIn(
            "TEST_COMMAND",
            text,
            "SKILL.md must reference TEST_COMMAND as the source for "
            "acceptance_execution.command",
        )
        self.assertNotIn(
            "python3 -m pytest",
            text,
            "SKILL.md must not instruct authoring a hardcoded runner",
        )


if __name__ == "__main__":
    unittest.main()
