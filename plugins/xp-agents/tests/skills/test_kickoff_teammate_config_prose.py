#!/usr/bin/env python3
"""Pin: xp-kickoff SKILL.md offers the teammate-config opt-in in the Sprint fork.

story-001. The Sprint session fork must ask the user about teammate support
(on/off) then default model tier, and write the result via teammate_config_cli.py.
The Free session fork must NOT ask — teammates require a sprint.
Prose must be declarative and project-agnostic: no internal marker filenames
or constant names in the shipped skill text.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import tier_wire
from conftest import _slice, _split_frontmatter_body

_SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-kickoff" / "SKILL.md"


class TestKickoffTeammateConfigProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        cls.sprint_fork = _slice(cls.body, "### Sprint session fork", ("## Step",))
        cls.free_fork = _slice(
            cls.body, "### Free session fork", ("### Sprint session fork",)
        )
        cls.frontmatter, _ = _split_frontmatter_body(_SKILL_PATH.read_text())

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_sprint_fork_asks_teammate_support(self):
        """AC#1: Sprint fork asks On/Off for teammate support via AskUserQuestion."""
        self.assertIn("AskUserQuestion", self.sprint_fork)
        self.assertRegex(self.sprint_fork, r"(?i)teammate")

    def test_sprint_fork_asks_on_off_options(self):
        """Sprint fork presents On and Off as options."""
        self.assertIn("On", self.sprint_fork)
        self.assertIn("Off", self.sprint_fork)

    def test_sprint_fork_asks_default_model_question(self):
        """Sprint fork asks a second question about default model tier."""
        self.assertRegex(self.sprint_fork, r"(?i)model")

    def test_sprint_fork_writes_via_teammate_config_cli(self):
        """AC#1: The answer is recorded via teammate_config_cli.py write."""
        self.assertIn("teammate_config_cli.py", self.sprint_fork)
        self.assertRegex(self.sprint_fork, r"teammate_config_cli\.py.*write")

    def test_sprint_fork_covers_all_tokens(self):
        """Every canonical config token appears in the Sprint fork.

        Bound to tier_wire so a new tier (e.g. fable) can't be added to the
        vocabulary without also being offered here.
        """
        for token in tier_wire.TEAMMATE_CONFIG_TOKENS:
            self.assertIn(token, self.sprint_fork, f"token {token!r} missing")

    def test_free_fork_has_no_teammate_question(self):
        """AC#2: Free session fork never asks about teammate support."""
        self.assertNotRegex(self.free_fork, r"(?i)teammate")
        self.assertNotIn("teammate_config_cli", self.free_fork)

    def test_prose_uses_no_internal_marker_filename(self):
        """Declarative: internal marker filename must not appear in shipped prose."""
        self.assertNotIn(".teammate-config", self.sprint_fork)
        self.assertNotIn(".teammate-config", self.free_fork)

    def test_prose_uses_no_internal_constant_name(self):
        """Declarative: TEAMMATE_CONFIG constant name must not appear in prose."""
        self.assertNotIn("TEAMMATE_CONFIG", self.sprint_fork)
        self.assertNotIn("TEAMMATE_CONFIG", self.free_fork)

    def test_teammate_config_cli_in_allowed_tools(self):
        """teammate_config_cli.py must be in the skill's allowed-tools frontmatter."""
        self.assertIn("teammate_config_cli.py", self.frontmatter)


if __name__ == "__main__":
    unittest.main()
