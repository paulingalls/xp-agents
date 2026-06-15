#!/usr/bin/env python3
"""Pins for the /xp-schedule SKILL.md (story-002, the decide-half).

xp-schedule consumes the ready-frontier preload vars, asks solo/parallel only
on a >=2 disjoint frontier (auto-solo otherwise), promotes the chosen frontier
scheduled->in-progress, and sets each story's execution_mode. These pins keep
the skill's authoring prose honest about that contract.
"""

import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-schedule" / "SKILL.md"
)


class TestScheduleSkillProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_PATH.read_text()
        cls.frontmatter, cls.body = _split_frontmatter_body(cls.text)

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_frontmatter_names_xp_schedule(self):
        self.assertIn("name: xp-schedule", self.frontmatter)

    def test_is_inline_not_forked(self):
        # Interactive (AskUserQuestion) → inline; auto-discovery suites enforce
        # the Sequential-discipline pin only on inline skills.
        self.assertNotIn("context: fork", self.frontmatter)

    def test_self_wires_preload(self):
        self.assertIn("scripts/preload.sh", self.body)

    def test_has_sequential_discipline_pin(self):
        self.assertIn("Sequential discipline", self.body)

    def test_consumes_frontier_vars(self):
        self.assertIn("FRONTIER_COUNT", self.body)
        self.assertIn("PARALLELIZABLE", self.body)

    def test_asks_solo_or_parallel(self):
        self.assertIn("AskUserQuestion", self.body)

    def test_sets_execution_mode(self):
        self.assertIn("execution_mode", self.body)

    def test_promotes_to_in_progress(self):
        self.assertIn("in-progress", self.body)


if __name__ == "__main__":
    unittest.main()
