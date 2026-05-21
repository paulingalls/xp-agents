#!/usr/bin/env python3
"""Pin: xp-plan SKILL.md nudges behavior-shaped milestone acceptance.

The Definition of Done authoring step must steer authors toward
behavior-shaped acceptance (Given/When/Then or equivalent) so milestone
`done` reads as an observable outcome, not an implementation note.
"""

import re
import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-plan" / "SKILL.md"


class TestXpPlanBehaviorShapeProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Assert on the body only — a frontmatter `description` match would
        # false-pass without the authoring prose ever carrying the nudge.
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_definition_of_done_nudges_behavior_shape(self):
        # The Definition of Done bullet must mention a behavior shape.
        dod_line = next(
            (ln for ln in self.body.splitlines() if "Definition of Done" in ln),
            None,
        )
        self.assertIsNotNone(dod_line, "no 'Definition of Done' bullet found")
        assert dod_line is not None  # narrow for the type-checker
        self.assertRegex(
            dod_line,
            r"(?i)given/when/then|behavior-shaped",
            "Definition of Done must nudge a behavior shape (Given/When/Then"
            " or equivalent)",
        )

    def test_given_when_then_present_in_body(self):
        self.assertTrue(
            re.search(r"(?i)given/when/then", self.body),
            "SKILL.md should reference the Given/When/Then behavior shape",
        )


if __name__ == "__main__":
    unittest.main()
