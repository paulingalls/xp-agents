#!/usr/bin/env python3
"""Pins for the /xp-sprint-start File Domain bullet's lifecycle scoping.

A file-domain claim is scoped to the window in which its story is running --
its purpose is to keep two stories that run at the same time off one file, not
to grant a story permanent title to it. So three kinds of claimant hold
nothing: one that finished, one that was dropped, and one that never started.
A planner who cannot see that in the bullet has no sanctioned way to re-touch
such a file except by inventing a dependency that does not exist.

These pins keep the bullet honest about the rule and about the reason for it,
without pinning exact wording. The earlier version of this module pinned
"owns while it runs" verbatim, and that phrasing is what a later story had to
replace -- so the assertions here name the CONCEPT (claims, running, the
concurrency reason, each exempt lifecycle state) and leave the sentence free.
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

    def test_states_every_non_running_state_is_exempt(self):
        # Three lifecycle states hold nothing. Finished and dropped were
        # already named; never-started is the one the ownership framing hid,
        # and the one a planner most needs, since a queued story may never run.
        for state in ("finished", "dropped", "never-started"):
            self.assertIn(
                state,
                self.body_lower,
                f"File Domain bullet must name the {state} claimant as exempt",
            )
        # "no dependency edge", not "no dependency" -- the bare substring is
        # already satisfied by the pre-existing "Stories with no dependency
        # between them", so it could never go red on a dropped clause.
        self.assertIn("no dependency edge", self.body_lower)

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
