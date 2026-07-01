#!/usr/bin/env python3
"""Pin: xp-kickoff SKILL.md offers the review-cadence opt-in in the Sprint fork.

story-004. The Sprint session fork must ask the user for commit vs story
cadence and write 'story' (via write_review_cadence) only on the story choice.
The Free session fork must NOT ask — cadence is a sprint concern.
"""

import unittest
from pathlib import Path

from conftest import _slice, _split_frontmatter_body

_SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-kickoff" / "SKILL.md"


class TestKickoffCadenceProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        cls.sprint_fork = _slice(cls.body, "### Sprint session fork", ("## Step",))
        cls.free_fork = _slice(
            cls.body, "### Free session fork", ("### Sprint session fork",)
        )

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_sprint_fork_offers_cadence_choice(self):
        """AC#1: Sprint fork asks commit vs story via AskUserQuestion."""
        self.assertIn("AskUserQuestion", self.sprint_fork)
        self.assertRegex(self.sprint_fork, r"(?i)review cadence")
        self.assertIn("commit", self.sprint_fork)
        self.assertIn("story", self.sprint_fork)

    def test_story_write_is_conditional(self):
        """AC#1: writes 'story' via cadence_cli.py, gated on the choice."""
        self.assertIn("cadence_cli.py", self.sprint_fork)
        self.assertRegex(self.sprint_fork, r"cadence_cli\.py.*write story")
        # The write must be conditional on the story choice, not unconditional.
        self.assertRegex(self.sprint_fork, r"(?i)only when.*story")

    def test_free_fork_has_no_cadence_question(self):
        """AC#2: the Free session fork never asks about cadence."""
        self.assertNotRegex(self.free_fork, r"(?i)review cadence")
        self.assertNotIn("cadence_cli", self.free_fork)


if __name__ == "__main__":
    unittest.main()
