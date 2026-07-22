#!/usr/bin/env python3
"""Pins on xp-assign SKILL.md prose that a consuming mechanism depends on.

Each class here pins prose whose wording (or ordering) is load-bearing for code
elsewhere: the prompt-write step's verbatim branch (the spawn's refusal gate),
pre-flight mode selection order (the preload's SOLO_TARGET emission), and the
signal the stale-spawn check keys on.

## Prompt-write step: the story branch VERBATIM.

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


class TestAssignPreflightModeProse(unittest.TestCase):
    """story-008: pre-flight mode selection is SOLO-FIRST, and drains.

    The preload surfaces a lone in-progress solo story as SOLO_TARGET even when
    a teammate batch is live. That is inert unless mode selection reads it
    first: the old teammate-first order reached the SOLO_TARGET branch only when
    the batch was empty — precisely the state where the solo story was the only
    candidate anyway. The two legs are load-bearing only together, so the prose
    order is pinned here alongside the preload's emission pin
    (test_assign_preload_tier_target.py).
    """

    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        cls.preflight = _slice(cls.body, "## Pre-flight", ("## Step 0",))

    def test_solo_is_selected_before_the_teammate_batch(self):
        """SOLO_TARGET must be tested BEFORE TEAMMATE_STORY_IDS. Ordering is the
        whole fix: reversed, the solo branch is unreachable whenever a batch is
        live, which is the state that needs routing."""
        solo = self.preflight.find("SOLO_TARGET")
        batch = self.preflight.find("TEAMMATE_STORY_IDS")
        self.assertNotEqual(solo, -1, "pre-flight does not mention SOLO_TARGET")
        self.assertNotEqual(batch, -1, "pre-flight does not mention TEAMMATE_STORY_IDS")
        self.assertLess(
            solo,
            batch,
            "mode selection must read SOLO_TARGET first — teammate-first makes "
            "the solo branch unreachable on a mixed frontier",
        )

    def test_the_solo_story_drains_before_the_batch_resumes(self):
        """No fall-through: while a solo story is live, every invocation targets
        it. The prose must say so, or a lead reading 'solo-first' as a tiebreak
        will fall through to the batch on the next run."""
        self.assertRegex(self.preflight, r"(?i)drain")

    def test_the_safety_rationale_for_draining_is_stated(self):
        """WHY it is not merely an ordering preference: a teammate spawn checks
        out the base branch in the main checkout, where an in-place solo
        teammate is concurrently committing. An unstated rationale gets
        'optimized' back into a fall-through by the next editor."""
        self.assertRegex(self.preflight, r"(?i)checkout")
        self.assertRegex(self.preflight, r"(?i)in.place|solo")

    def test_the_hole_in_the_drain_is_stated_not_papered_over(self):
        """>1 in-progress solo empties SOLO_TARGET, and empty is exactly what
        "no solo story" looks like — so the drain has a hole the preload cannot
        close. Prose that asserts the invariant unconditionally claims a
        guarantee the code does not hold, and the lead acts on the claim: it
        selects the batch and Step 2 checks out the base in the very checkout
        the solo teammate is committing in. The caveat is the guard."""
        self.assertRegex(
            self.preflight,
            r"(?i)>\s*1 in-progress solo|more than one.{0,40}solo",
            "pre-flight asserts the drain without naming the state that breaks "
            "it — an unqualified invariant the preload cannot deliver",
        )
        self.assertRegex(
            self.preflight,
            r"(?i)reconcile|accept or defer",
            "naming the hole without an action leaves the lead to fall through",
        )

    def test_draining_is_reconciled_with_the_spawn_first_precedence(self):
        """Draining makes the batch's next spawn WAIT on an accept, which the
        intro's 'plan -> SPAWN -> accept ... spawning never waits on an accept'
        forbids. Two rules that contradict each other leave the lead to pick,
        so the pre-flight must name this as that precedence's one exception."""
        self.assertRegex(self.preflight, r"(?i)precedence")


class TestAssignStaleSpawnCheckProse(unittest.TestCase):
    """The stale-spawn check must key on a signal that actually exists.

    It previously told the lead to look for a `session_init` event referencing
    the story. No such event type exists anywhere in the codebase, so the lookup
    always came back empty and the check always concluded "genuinely
    un-spawned" — it read as evidence while carrying none, and misled the lead
    into re-targeting a story twice in one session. A check that cannot fail is
    worse than no check.
    """

    @classmethod
    def setUpClass(cls):
        cls.frontmatter, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())

    def test_no_nonexistent_event_type_is_cited(self):
        self.assertNotIn(
            "session_init",
            self.body,
            "the stale-spawn check cites an event type this codebase never "
            "emits, so the lookup is always empty and the check always passes",
        )

    def test_allowed_tools_permits_the_replacement_check(self):
        """The replacement signal must be one this skill can actually read.
        xp-assign grants no bare Bash, so a merged-branch check the frontmatter
        does not list is unrunnable — which is how the check it replaced became
        decorative in the first place."""
        self.assertIn("git branch --merged", self.frontmatter)
        self.assertIn("git branch --merged", self.body)

    def test_the_check_does_not_hinge_on_a_branch_the_close_deletes(self):
        """`git branch --merged` alone reproduces the defect it replaced. A
        completed /xp-story-close DELETES the story branch (close_common merge
        -> branching.delete_branch, and cleanup_teammate on the worktree path),
        so in the ordinary (c) the branch is gone and --merged lists nothing —
        reading as "un-spawned, go ahead". The discriminator that survives the
        delete is the story's recorded `branch_name`: set means Step 2 already
        cut a branch for it, whatever git still holds."""
        stale = _slice(self.body, "**Stale-spawn check.**", ("## Step 0",))
        self.assertIn("branch_name", stale)
        self.assertRegex(stale, r"(?i)delete")


if __name__ == "__main__":
    unittest.main()
