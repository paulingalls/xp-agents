#!/usr/bin/env python3
"""Integration tests for the LAST_SESSION section in xp-kickoff preload.

Story-002 of sprint-072: check_session_needs.sh invokes render_history.py
between the NEEDS_SYSTEM_CONTEXT and NEEDS_EXECUTION_PLAN sections so the
last 1-2 session summaries appear in the kickoff preload when
session_history.json exists. Section is silent when the file is absent.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import session_history
from _bases import _PLUGIN_ROOT
from _branching_fixtures import write_system_context
from conftest import _IntegrationTestCase, make_session_history_entry

_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-kickoff" / "scripts" / "check_session_needs.sh"


class TestKickoffHistoryRender(_IntegrationTestCase):
    """check_session_needs.sh emits the LAST_SESSION section when history exists."""

    def setUp(self):
        super().setUp()
        self.assertTrue(_PRELOAD.is_file(), f"Preload script missing: {_PRELOAD}")
        write_system_context(self.smm_dir, stage=1)

    def test_no_section_when_no_history_file(self):
        result = self._run_preload(_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("### LAST_SESSION", result.stdout)

    def test_section_renders_content_and_appears_before_needs_execution_plan(self):
        session_history.save_history(
            self.smm_dir,
            {
                "version": session_history.SCHEMA_VERSION,
                "entries": [
                    make_session_history_entry(
                        ts="2026-05-07T10:00:00+00:00",
                        summary="Shipped session_history pipeline.",
                        carry_forward=[
                            {
                                "note": "Wire kickoff render next session.",
                                "references": ["abc123def456"],
                                "recommendation": "Pick up story-001 first.",
                            }
                        ],
                    )
                ],
            },
        )

        result = self._run_preload(_PRELOAD)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("### LAST_SESSION", result.stdout)
        self.assertIn("Shipped session_history pipeline.", result.stdout)
        self.assertIn("Wire kickoff render next session.", result.stdout)
        self.assertIn("Pick up story-001 first.", result.stdout)
        self.assertIn("### NEEDS_EXECUTION_PLAN", result.stdout)
        self.assertLess(
            result.stdout.index("### LAST_SESSION"),
            result.stdout.index("### NEEDS_EXECUTION_PLAN"),
        )


if __name__ == "__main__":
    unittest.main()
