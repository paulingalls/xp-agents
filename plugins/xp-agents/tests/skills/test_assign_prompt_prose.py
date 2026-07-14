#!/usr/bin/env python3
"""Pin: xp-assign's prompt-write step requires the story branch VERBATIM.

story-014. The spawn now REFUSES a prompt that does not name the branch it is
spawning on — that is what stops a stale prompt from a same-numbered story in
another sprint being fed to a teammate.

That gate is only as good as the prose that feeds it. Step 3 previously just
ASKED the lead to include "Story Branch — the branch name created in Step 2";
nothing pinned the literal string. A lead who wrote a shortened or prettified
form ("story-003", "the story-003 branch") would make EVERY spawn refuse — the
gate would be correct and the workflow would be dead. So the prose must demand
the branch exactly as it is passed to --branch, and this test is what keeps the
two legs of that contract from drifting apart.

Sibling of test_assign_tier_prose.py (Step 0's behavior table); precedent for
pinning a skill's prose against the code that consumes it: test_pipeline_order_
prose.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _slice, _split_frontmatter_body

_SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-assign" / "SKILL.md"


class TestAssignPromptProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        cls.write_step = _slice(
            cls.body,
            "## Step 3: Write the prompt file for THIS story",
            ("## Step 4",),
        )

    def test_the_prompt_must_carry_the_story_branch(self):
        """The spawn asserts on the BRANCH, so the prompt must carry it."""
        self.assertIn("Story Branch", self.write_step)

    def test_the_branch_must_be_demanded_verbatim(self):
        """Not 'the branch name' — the EXACT string, unabbreviated and
        unreformatted. Anything the lead paraphrases fails the spawn's check."""
        self.assertRegex(
            self.write_step,
            r"(?i)verbatim|exactly as|exact string|character.for.character",
        )

    def test_it_is_the_story_branch_not_the_sprint_branch(self):
        """sprint.json carries a sprint-level `branch_name` AND a per-story one.
        The worktree is cut on the STORY branch and that is what --branch gets,
        so naming the sprint branch in the prompt would refuse every spawn."""
        self.assertRegex(self.write_step, r"(?i)story branch|story's branch")
        self.assertRegex(
            self.write_step,
            r"(?is)same.{0,40}--branch|--branch.{0,60}Step 4|passed to `?--branch",
            "the prose must tie the prompt's branch to the --branch flag the "
            "spawn is given — they are asserted equal",
        )

    def test_the_consequence_of_omitting_it_is_stated(self):
        """A rule whose failure mode is unstated gets 'improved' by the next
        editor. Say that the spawn refuses without it."""
        self.assertRegex(self.write_step, r"(?i)refus|reject|will not spawn")

    def test_the_stale_prompt_hazard_is_named(self):
        """The WHY: story ids repeat every sprint, so a prompt that names only
        the id cannot be told apart from last sprint's same-numbered story."""
        self.assertRegex(self.write_step, r"(?i)stale|another sprint|repeat")

    def test_the_in_place_variant_is_not_left_contradicting_the_gate(self):
        """Step 4's solo variant passes NO --branch. Left unsaid, Step 3's
        "the spawn refuses any prompt without the --branch string" reads as
        false there — and a lead who spots the contradiction is free to
        conclude the whole branch line is optional for a solo spawn. Say that
        the check degrades to the story id instead, and that the branch is
        still written."""
        self.assertRegex(self.write_step, r"(?i)in.place")
        self.assertRegex(self.write_step, r"(?i)story id|story.ID")


if __name__ == "__main__":
    unittest.main()
