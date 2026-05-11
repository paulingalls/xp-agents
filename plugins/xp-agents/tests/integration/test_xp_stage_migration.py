#!/usr/bin/env python3
"""Integration tests for xp-stage-migration SKILL.md prose contract.

The Stage 2 floor migration prompt was extracted from xp-kickoff Step 2.4
into its own skill so kickoff doesn't pay the ~430-token tax every session
for a step that fires at most once per project. This file pins the prose
the new skill must carry to preserve the original Step 2.4 behavior.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-stage-migration" / "SKILL.md"


class TestXpStageMigrationSkill(unittest.TestCase):
    """xp-stage-migration carries the migrate/continue/dismiss contract."""

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text()

    def test_skill_reads_branching_stage(self):
        self.assertIn("branching.py", self.text)
        self.assertIn("stage", self.text.lower())

    def test_skill_uses_askuser_question(self):
        self.assertIn("AskUserQuestion", self.text)

    def test_skill_offers_migrate_or_continue(self):
        lower = self.text.lower()
        self.assertIn("migrate", lower)
        self.assertIn("continue", lower)

    def test_skill_dispatches_sprint_start_on_migrate(self):
        self.assertIn("/xp-sprint-start", self.text)

    def test_skill_records_dismissal_on_continue(self):
        self.assertIn("stage_prompt_dismissed_at", self.text)
        self.assertIn("edit-branching-field", self.text)

    def test_skill_logs_dismissed_at_when_already_set(self):
        lower = self.text.lower()
        self.assertIn("dismissed", lower)


if __name__ == "__main__":
    unittest.main()
