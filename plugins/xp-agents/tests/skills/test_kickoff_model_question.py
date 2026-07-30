#!/usr/bin/env python3
"""Pin: xp-kickoff Q2 'Default model for teammates?' stays within the
AskUserQuestion 4-option cap.

AskUserQuestion accepts at most 4 options; a 5th trips an InputValidationError
on the first call, forcing a retry every session. Q2 previously listed 5 model
choices (haiku/sonnet/opus/fable/inherit). The fix keeps 4 button options and
routes the least-necessary tier (fable) to the tool's automatic 'Other'
free-text escape, so no capability is lost. This test guards the cap and the
escape so a future edit can't silently re-add a 5th button.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _slice

_SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-kickoff" / "SKILL.md"

# AskUserQuestion hard limit — see the tool schema (options maxItems: 4).
_MAX_OPTIONS = 4


class TestKickoffModelQuestion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        body = _SKILL_PATH.read_text()
        # Isolate the Q2 option list: from the question line to the write block.
        cls.section = _slice(
            body,
            '"Default model for teammates?"',
            # "matching" until story-004: no such string exists in the skill
            # (it says "chosen"), so the slice silently ran to EOF and the
            # option cap below was enforced over the whole rest of the file.
            # It passed only because Steps 3-7 happen to contain no "- **"
            # bullets — the next one added would have failed for the wrong
            # reason. Same defect class as the scan-less-than-claimed pins.
            ("Write the chosen token",),
        )

    def _option_bullets(self):
        """Bulleted options are '- **token**' lines in the Q2 section."""
        return [
            ln for ln in self.section.splitlines() if ln.lstrip().startswith("- **")
        ]

    def test_at_most_four_button_options(self):
        bullets = self._option_bullets()
        self.assertLessEqual(
            len(bullets),
            _MAX_OPTIONS,
            f"Q2 lists {len(bullets)} button options, over the AskUserQuestion "
            f"cap of {_MAX_OPTIONS}: {bullets!r}",
        )

    def test_recommended_default_present(self):
        self.assertIn("sonnet", self.section)
        self.assertIn("Recommended", self.section)

    def test_dropped_tier_reachable_via_other(self):
        """fable is dropped from the buttons but must stay reachable, so the
        section must name it alongside the 'Other' escape — losing it silently
        would remove the top tier."""
        self.assertIn("fable", self.section)
        self.assertIn("Other", self.section)


if __name__ == "__main__":
    unittest.main()
