#!/usr/bin/env python3
"""Pin: spawnable work goes out FIRST; accept only what is left over.

story-011 (ad-hoc). xp-assign's post-spawn prose used to tell the lead to
"pause planning to accept the one that just finished" once a task-notification
fires — the inversion of the pipeline's whole point (a teammate should always
be running in the background). The rule is precedence, not deferral: spawn
any planned/reviewed/un-spawned story FIRST, then accept; only when nothing
is left to spawn does the accept happen immediately (the AC2 escape clause —
without it, a naive "never accept before spawning" reading would stall
acceptance forever once the frontier empties, which is worse than the bug
being fixed).

xp-accept's real hole is the accept LOOP (Step 1.5 -> Step 4, over plural
`reviewing` stories) — a lead arriving on a task-notification lands there and
can drain a whole finish-burst without ever reaching Step 8's post-loop
handoff. So the precedence rule belongs at xp-accept's ENTRY (pre-flight /
before Step 1), not bolted onto Step 8 (which already routes into
/xp-assign and editing it alone would be close to a no-op).

The negative pin is scoped to the SHAPE of the inversion (a hold/pause/wait/
defer verb governing plan/spawn "to accept"), not a body-wide token scan —
xp-accept uses defer/deferred ~20 times as the story-disposition vocabulary
(mark deferred, cascade a deferral) and xp-assign:265 uses "wait" as a
mandatory shared-checkout safety constraint for the solo in-place variant.
Neither is the pipeline inversion; a token-level pin would false-positive on
both and get weakened until it caught nothing.
"""

import re
import unittest
from pathlib import Path

from conftest import _slice, _split_frontmatter_body

_ASSIGN_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-assign" / "SKILL.md"
_ACCEPT_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-accept" / "SKILL.md"

# Matches the offending SHAPE: a hold/pause/wait/defer verb governing a
# plan/spawn noun, in order to accept — e.g. "pauses planning to accept".
# Deliberately does NOT match "before accepting" (the correct ordering rule)
# or bare "defer"/"wait" used for unrelated things (story disposition,
# solo-checkout safety) since those never sit next to "to accept".
_INVERTED_SHAPE_RE = re.compile(
    r"(?i)\b(?:pauses?|pausing|holds?\s+off|holding\s+off|defers?|deferring|"
    r"stalls?|stalling|waits?|waiting)\b"
    r"[^.]{0,80}?"
    r"\b(?:plan(?:s|ning)?|spawn(?:s|ing)?)\b"
    r"[^.]{0,60}?"
    r"\bto accept\b"
)


class TestPipelineOrderProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assign_frontmatter, cls.assign_body = _split_frontmatter_body(
            _ASSIGN_PATH.read_text()
        )
        cls.accept_frontmatter, cls.accept_body = _split_frontmatter_body(
            _ACCEPT_PATH.read_text()
        )
        # Scoped regions, per the trap warning: check the SHAPE only where the
        # inversion could plausibly live, not the whole body.
        cls.assign_post_spawn = _slice(cls.assign_body, "## Step 5: Post-spawn", ())
        cls.accept_entry = _slice(
            cls.accept_body,
            "# Accept Verification",
            ("## Step 1: Review Each Story Under Acceptance",),
        )

    def test_skill_files_exist(self):
        self.assertTrue(_ASSIGN_PATH.is_file())
        self.assertTrue(_ACCEPT_PATH.is_file())

    # --- AC3: the inverted shape must never appear -------------------------
    def test_assign_post_spawn_drops_inverted_shape(self):
        match = _INVERTED_SHAPE_RE.search(self.assign_post_spawn)
        self.assertIsNone(
            match,
            f"inverted pause/defer-to-accept shape in xp-assign post-spawn: {match}",
        )

    def test_accept_entry_drops_inverted_shape(self):
        match = _INVERTED_SHAPE_RE.search(self.accept_entry)
        self.assertIsNone(
            match,
            f"inverted pause/defer-to-accept shape found in xp-accept entry: {match}",
        )

    def test_inverted_shape_regex_matches_the_original_bug(self):
        """The regex isn't a no-op: it matches the exact sentence this story
        replaces, so a future revert of the fix is caught, not silently missed."""
        original_bug_sentence = (
            "when a notification arrives, the lead pauses planning to accept "
            "the one that just finished."
        )
        self.assertIsNotNone(_INVERTED_SHAPE_RE.search(original_bug_sentence))

    def test_regex_does_not_false_positive_on_defer_disposition_vocab(self):
        """xp-accept's story-disposition vocabulary (mark deferred, cascade a
        deferral) must not trip the pin — it has nothing to do with pipeline
        order."""
        self.assertIsNone(
            _INVERTED_SHAPE_RE.search(
                "Move to `deferred`. If the story has downstream dependents, "
                'cascade the deferral (see "Cascading a deferral").'
            )
        )

    def test_regex_does_not_false_positive_on_solo_wait_safety_constraint(self):
        """xp-assign's solo in-place `wait` is a shared-checkout safety
        constraint (no edits until the notification fires), not the pipeline
        inversion — must not trip the pin."""
        self.assertIsNone(
            _INVERTED_SHAPE_RE.search(
                "`run_in_background=true`, then **wait**: end your turn and "
                "make NO edits in the main checkout until the task-notification "
                "fires (it commits to the solo branch in place). On it, run "
                "`/xp-accept` for `$TARGET`."
            )
        )

    # --- AC1: plan -> SPAWN -> accept ordering rule in xp-assign ------------
    def test_assign_states_plan_spawn_accept_order(self):
        self.assertIn("plan → SPAWN → accept", self.assign_body)

    def test_assign_post_spawn_tells_lead_to_spawn_before_accepting(self):
        self.assertRegex(
            self.assign_post_spawn,
            r"(?is)spawn it (?:first|FIRST)[^.]{0,60}then accept",
        )

    # --- AC2: empty-background escape must not stall acceptance ------------
    def test_assign_states_empty_frontier_accepts_immediately(self):
        self.assertRegex(
            self.assign_post_spawn,
            r"(?is)nothing\s+(?:is\s+)?left\s+to\s+spawn[^.]{0,60}accept[^.]{0,20}immediately",
        )

    # --- xp-accept: rule lives at the ENTRY, not bolted onto Step 8 ---------
    def test_accept_entry_states_precedence_rule(self):
        self.assertRegex(
            self.accept_entry,
            r"(?is)/xp-assign[^.]{0,80}spawn it first",
        )

    def test_accept_entry_states_empty_frontier_escape(self):
        self.assertRegex(
            self.accept_entry,
            r"(?is)nothing\s+(?:is\s+)?left\s+to\s+spawn[^.]{0,60}accept\s+immediately",
        )

    def test_accept_step_8_left_alone(self):
        """Step 8 is post-loop and already routes into /xp-assign; the fix
        must NOT be bolted on there instead of the entry (that would be close
        to a no-op — a lead draining the accept loop never reaches Step 8
        until every reviewing story is done)."""
        step_8 = _slice(self.accept_body, "## Step 8: Continue to next story", ())
        self.assertNotIn("spawn it first", step_8)


if __name__ == "__main__":
    unittest.main()
