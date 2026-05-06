#!/usr/bin/env python3
"""Pin: xp-plan-reviewer body must guide AC-command/file_domain coherence.

Sprint-065 story-006 shipped with `acceptance_execution.command` pointing at
a probe file that did not exercise the new code — the AC command was green
without testing anything the story added. Per decision 250ba9657966 the fix
is prompt-side: xp-plan-reviewer parses each story's `acceptance_execution`
command(s) and verifies at least one pytest path lives inside (or equals) a
path in the story's `file_domain`. When none intersect, it emits a concern.

This pin keeps the guidance in the agent body (visible to the LLM) — not in
the frontmatter (where literal-text matches in `assertIn` would false-pass
without the agent ever reading it).
"""

import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_AGENT_PATH = Path(__file__).parent.parent.parent / "agents" / "xp-plan-reviewer.md"


class TestPlanReviewerPin(unittest.TestCase):
    """xp-plan-reviewer.md body MUST direct an AC-command/file_domain check."""

    @classmethod
    def setUpClass(cls):
        cls.frontmatter, cls.body = _split_frontmatter_body(_AGENT_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_agent_file_exists(self):
        self.assertTrue(
            _AGENT_PATH.is_file(),
            f"missing agent file: {_AGENT_PATH}",
        )

    def test_body_pairs_acceptance_execution_with_file_domain(self):
        # Both literals must appear in the BODY (not just frontmatter) so the
        # agent prompt actually instructs the coherence check at review time.
        # Frontmatter `description` mentions could false-pass an `assertIn` on
        # the full file text — splitting on `---` prevents that escape.
        self.assertIn(
            "acceptance_execution",
            self.body,
            "xp-plan-reviewer body must reference `acceptance_execution` so "
            "the agent knows which story field to parse for AC commands",
        )
        self.assertIn(
            "file_domain",
            self.body,
            "xp-plan-reviewer body must reference `file_domain` so the agent "
            "knows which story field to intersect AC paths against",
        )

    def test_body_describes_intersection_check(self):
        # The pairing alone is not enough — the body must direct the agent to
        # check whether AC paths intersect file_domain. Pin a synonym set so a
        # phrasing tweak doesn't break the pin, but a missing instruction does.
        intersection_synonyms = ("intersect", "inside", "within", "overlap")
        self.assertTrue(
            any(token in self.body_lower for token in intersection_synonyms),
            "xp-plan-reviewer body must direct the agent to check whether "
            "AC pytest paths intersect (or live inside / overlap) the "
            f"story's file_domain — none of {intersection_synonyms} found",
        )

    def test_body_directs_concern_on_mismatch(self):
        # The check is only useful if a mismatch is recorded as a concern —
        # otherwise the AC drift escapes a future review the same way it did
        # in sprint-065 story-006.
        self.assertIn(
            "concern",
            self.body_lower,
            "xp-plan-reviewer body must direct the agent to emit a concern "
            "when AC paths do not intersect file_domain",
        )

    def test_body_covers_unittest_discover(self):
        # The codebase uses `python -m unittest discover -s <path>` as a
        # sequential fallback (see CLAUDE.md Testing). If the guidance only
        # extracts pytest tokens, an AC using unittest discover with a probe
        # path silently escapes the coherence check.
        self.assertIn(
            "unittest discover",
            self.body_lower,
            "xp-plan-reviewer body must include unittest discover in its "
            "AC-path extraction guidance, or unittest-style ACs slip through",
        )

    def test_body_covers_direct_script_invocations(self):
        # Section 10b also covers `python <path>` / `bash <path>` direct
        # script invocations as AC commands. Pin a token from that line so
        # a future trim of the bullet list can't silently drop it (symmetric
        # coverage with the unittest-discover pin above).
        self.assertIn(
            "direct script invocations",
            self.body_lower,
            "xp-plan-reviewer body must include direct script invocations "
            "(python/bash <path>) in its AC-path extraction guidance",
        )


if __name__ == "__main__":
    unittest.main()
