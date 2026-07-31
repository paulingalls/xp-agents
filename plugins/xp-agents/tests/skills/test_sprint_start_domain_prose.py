#!/usr/bin/env python3
"""Pins for the /xp-sprint-start File Domain bullet's lifecycle scoping.

A file-domain claim is scoped to the window in which its story is running --
its purpose is to keep two stories that run at the same time off one file, not
to grant a story permanent title to it. A finished or dropped claimant holds
nothing, so re-touching its file needs no invented dependency.

A never-started claimant is the one the bullet must be CAREFUL about, because
this skill authors the sprint. The authoring write is where disjointness is
decided, and every story being authored has yet to run -- so the authoring
write holds all of their claims. Only a later, mid-sprint amendment asks the
narrower question of which stories are actually in flight. A bullet that told
the planner a never-started claim never collides would contradict the sentence
directly above it ("the sprint write refuses the collision") and send the
planner into a refused `create`.

These pins keep the bullet honest about the rule and about the reason for it,
without pinning exact wording. The earlier version of this module pinned
"owns while it runs" verbatim, and that phrasing is what a later story had to
replace -- so the assertions here name the CONCEPT (claims, running, the
concurrency reason, each lifecycle state and which side it falls on) and leave
the sentence free.
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

    def test_states_the_terminal_states_are_exempt(self):
        # Finished and dropped hold nothing on every path, authoring included.
        for state in ("finished", "dropped"):
            self.assertIn(
                state,
                self.body_lower,
                f"File Domain bullet must name the {state} claimant as exempt",
            )
        # "no dependency edge", not "no dependency" -- the bare substring is
        # already satisfied by the pre-existing "Stories with no dependency
        # between them", so it could never go red on a dropped clause.
        self.assertIn("no dependency edge", self.body_lower)

    def test_never_started_is_named_as_still_holding_at_authoring(self):
        """The bullet must NOT tell the planner a never-started claim is free
        to share. Every story in the sprint being authored is never-started,
        so that reading would make the refusal two sentences earlier
        unreachable -- and the planner would learn it from a failed `create`.
        """
        self.assertIn("never-started", self.body_lower)
        self.assertNotRegex(
            self.body,
            r"(?i)finished,?\s+dropped,?\s+or\s+never-started[^.]*never collides",
            "authoring holds a never-started claim; the bullet must not "
            "lump it in with the terminal exemptions",
        )
        self.assertRegex(
            self.body_lower,
            r"(?i)authoring is where disjointness is decided",
            "the bullet must say WHY authoring holds every claim",
        )

    def test_frames_the_claim_as_lifecycle_scoped_not_as_ownership(self):
        # The bullet must say the claim applies WHILE THE STORY RUNS. "owns"
        # invites a planner to read a queued story's list as a reservation,
        # which is exactly the false refusal this framing removes.
        self.assertIn("claims while it runs", self.body_lower)
        self.assertNotIn("owns while it runs", self.body_lower)

    def test_names_concurrency_as_the_reason(self):
        # Without the reason, "disjoint domains" reads as bureaucracy and gets
        # worked around. The bullet must say what goes wrong: two stories
        # running at once on one file.
        self.assertIn("never run at the same time", self.body)
        self.assertIn("step on each other", self.body_lower)
        self.assertIn("declare the dependency and share the path", self.body)

    def test_project_agnostic_no_internal_identifiers(self):
        # No internal surface name may leak into shipped prose.
        self.assertNotIn("TERMINAL_STORY_STATUSES", self.body)
        self.assertNotIn("collision_report", self.body)
        self.assertNotIn("_concurrent", self.body)


if __name__ == "__main__":
    unittest.main()
