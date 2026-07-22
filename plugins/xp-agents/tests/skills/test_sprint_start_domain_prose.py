#!/usr/bin/env python3
"""Pins for the /xp-sprint-start File Domain bullet's terminal-story exemption.

`file_domain_lock.collision_report` treats a claim held by a done/deferred
story as non-colliding, same as a dependency edge -- see
`smm/file_domain_lock.py`'s `_concurrent`/`collision_report` docstrings. The
shipped File Domain bullet named only the dependency-edge exemption, so a
planner re-touching an already-completed story's file had no sanctioned way
to declare it without inventing a dependency that doesn't exist. These pins
keep the bullet honest about both exemptions without pinning exact wording.
"""

import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-sprint-start" / "SKILL.md"
)


class TestSprintStartDomainProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_PATH.read_text()
        cls.frontmatter, cls.body = _split_frontmatter_body(cls.text)
        cls.body_lower = cls.body.lower()

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_states_terminal_story_exemption(self):
        # A claim held by a done/deferred story must be documented as
        # non-colliding -- no dependency edge required to re-touch it.
        self.assertTrue(
            "done or deferred" in self.body_lower or "done/deferred" in self.body_lower,
            "File Domain bullet must name the done/deferred exemption",
        )
        # "no dependency edge", not "no dependency" -- the bare substring is
        # already satisfied by the pre-existing "Stories with no dependency
        # between them", so it could never go red on a dropped clause.
        self.assertIn("no dependency edge", self.body_lower)

    def test_preserves_concurrent_disjointness_wording(self):
        # Characterization: the existing dependency-edge exemption sentences
        # must survive verbatim -- this is additive, not a rewrite.
        self.assertIn("owns while it runs", self.body)
        self.assertIn("never run at the same time", self.body)
        self.assertIn("declare the dependency and share the path", self.body)

    def test_project_agnostic_no_internal_identifiers(self):
        # No internal surface name may leak into shipped prose.
        self.assertNotIn("TERMINAL_STORY_STATUSES", self.body)
        self.assertNotIn("collision_report", self.body)
        self.assertNotIn("_concurrent", self.body)


if __name__ == "__main__":
    unittest.main()
