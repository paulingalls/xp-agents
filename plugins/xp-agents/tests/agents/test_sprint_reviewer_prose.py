#!/usr/bin/env python3
"""Doctrine-prose pins for xp-sprint-reviewer's Step 2b milestone gate.

`_acceptance_execution.py`'s run-time contract gates on command PRESENCE, not
on `type`: a manual block with no command/commands is never shelled. Step 2b
used to say only "Run `setup` (if present) then `command` via Bash" with no
branch for a manual block that carries `steps` and no command — precisely the
shape the milestone-level manual-shape rule (story-003) now forces every new
manual milestone into. Unbranched, that instruction would shell an absent
`command`, or would be silently skipped with no path to pass/fail the gate at
all. These pins hold the branch in place: no command → judge against `steps`,
nothing shelled; command present → shell it exactly as before.

Same shape as test_plan_reviewer_prose.py: slice the doctrine section by
heading, then check for the markers within that slice (not file-wide) so a
partial gutting of the branch fails loud rather than passing on an unrelated
mention elsewhere in the file.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT, _slice, assert_project_agnostic

_SPRINT_REVIEWER_MD = _PLUGIN_ROOT / "agents" / "xp-sprint-reviewer.md"

_STEP_2B_HEADING = "## Step 2b: Milestone Acceptance Gate"
_STEP_2C_HEADING = "## Step 2c:"


class TestMilestoneGateCommandPresenceBranch(unittest.TestCase):
    """Step 2b must branch on command presence, not shell unconditionally."""

    _MISSING_HEADING = (
        f"xp-sprint-reviewer.md must keep the '{_STEP_2B_HEADING}' heading — "
        "the command-presence branch lives inside it"
    )

    @classmethod
    def setUpClass(cls):
        cls.body = _SPRINT_REVIEWER_MD.read_text()
        if _STEP_2B_HEADING not in cls.body:
            raise AssertionError(cls._MISSING_HEADING)
        cls.section = _slice(cls.body, _STEP_2B_HEADING, (_STEP_2C_HEADING,))
        cls.section_lower = cls.section.lower()

    def test_file_exists(self):
        self.assertTrue(
            _SPRINT_REVIEWER_MD.is_file(),
            f"agent prompt missing at {_SPRINT_REVIEWER_MD}",
        )

    def test_step_2b_heading_present(self):
        self.assertIn(_STEP_2B_HEADING, self.body, self._MISSING_HEADING)

    def test_branches_on_command_presence(self):
        self.assertIn(
            "command",
            self.section_lower,
            "Step 2b must still name `command`/`commands` — the branch that shells it",
        )
        self.assertIn(
            "steps",
            self.section_lower,
            "Step 2b must name `steps` — the branch a command-less manual "
            "block is judged against instead of being shelled",
        )

    def test_no_command_branch_shells_nothing(self):
        # The failure mode this pin exists to catch: an unbranched
        # instruction would either shell an absent `command` (a shell
        # error unrelated to the acceptance question) or skip the gate
        # silently. Either reads as the same exit-127-style false red/green
        # the story-level authoring rule was built to stop.
        self.assertTrue(
            any(
                phrase in self.section_lower
                for phrase in (
                    "nothing is shelled",
                    "nothing shelled",
                    "no command is run",
                )
            ),
            "Step 2b must say explicitly that the no-command branch shells "
            "nothing — otherwise a manual block with only `steps` has no "
            "stated behavior",
        )

    def test_no_command_branch_uses_judgment_against_steps(self):
        self.assertTrue(
            any(
                phrase in self.section_lower
                for phrase in ("your own judgment", "agent judgment", "your judgment")
            ),
            "Step 2b's no-command branch must direct the reviewer to use "
            "judgment (not a shelled command) to decide pass/fail",
        )

    def test_command_present_branch_still_shells_as_before(self):
        self.assertIn(
            "via bash",
            self.section_lower,
            "Step 2b's command-present branch must still say the command "
            "runs via Bash — run-time behavior for a grandfathered stored "
            "block is unchanged",
        )

    def test_both_branches_keep_the_three_options(self):
        # The fix/override/defer options must survive the split — they are
        # the same three regardless of which branch produced the red.
        for option in ("fix and re-run", "override with concern", "defer"):
            self.assertIn(
                option,
                self.section_lower,
                f"Step 2b must keep the {option!r} option available to "
                "both the command-present and no-command branches",
            )

    def test_rule_is_project_agnostic(self):
        assert_project_agnostic(self, self.section, "Step 2b")


if __name__ == "__main__":
    unittest.main()
