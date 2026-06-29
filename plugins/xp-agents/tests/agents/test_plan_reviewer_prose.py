#!/usr/bin/env python3
"""Doctrine-prose pin for xp-plan-reviewer's final-message structure.

Debt 5e180220db1a: the forked subagent's terminating message previously only
nudged the next step (e.g. "run /xp-assign"), so the main agent couldn't see
concerns/assumptions/blocking-questions without digging into events.jsonl.

The fix is prose-only — extend the agent prompt to require the reviewer to
end its reply with an enumerated summary covering all four. This test pins
the doctrine so a later edit can't silently strip the requirement (same
shape as test_sequential_pins.py).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_PLAN_REVIEWER_MD = _PLUGIN_ROOT / "agents" / "xp-plan-reviewer.md"

# Substring markers — match the formatter-stable text, not the bold markup
# (same rationale as test_sequential_pins.MARKER). Each marker must appear
# WITHIN the Final Message section, not just anywhere in the file: words
# like "Assumptions" (section 6 header) and "Blocking questions" (prose
# at lines 33/75/77) already appear elsewhere, so a file-wide substring
# check would let an individual-bullet gutting of Final Message slip
# through. Scoping the search to the section catches partial-deletion
# regressions, not just wholesale heading removal.
_REQUIRED_MARKERS = (
    "Concerns",
    "Assumptions",
    "Blocking questions",
    "Next step",
)

_FINAL_MESSAGE_HEADING = "## Final Message"


class TestPlanReviewerFinalMessage(unittest.TestCase):
    """Final-message contract surfaces concerns/assumptions/questions to main."""

    @classmethod
    def setUpClass(cls):
        cls.body = _PLAN_REVIEWER_MD.read_text()
        # Slice from "## Final Message" to the next "## " heading (or EOF)
        # so the marker check only inspects the section that owns the
        # doctrine. Falls back to empty string when the heading is absent
        # — test_final_message_section_present catches that case loudly.
        start = cls.body.find(_FINAL_MESSAGE_HEADING)
        if start == -1:
            cls.final_message_section = ""
        else:
            after = cls.body.find("\n## ", start + len(_FINAL_MESSAGE_HEADING))
            cls.final_message_section = (
                cls.body[start:] if after == -1 else cls.body[start:after]
            )

    def test_file_exists(self):
        self.assertTrue(
            _PLAN_REVIEWER_MD.is_file(),
            f"agent prompt missing at {_PLAN_REVIEWER_MD}",
        )

    def test_final_message_section_present(self):
        # An explicit return-message section makes the contract checkable;
        # the Output section alone is about the human-readable review body.
        self.assertIn(
            "Final Message",
            self.body,
            "xp-plan-reviewer.md must declare a 'Final Message' section "
            "so the doctrine for the return-to-main reply is discoverable.",
        )

    def test_required_blocks_named(self):
        missing = [m for m in _REQUIRED_MARKERS if m not in self.final_message_section]
        self.assertEqual(
            missing,
            [],
            "xp-plan-reviewer.md Final Message section must name each "
            f"required block; missing: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
