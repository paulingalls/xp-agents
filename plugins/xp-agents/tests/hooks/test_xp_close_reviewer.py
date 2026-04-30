#!/usr/bin/env python3
"""Tests for the xp-close-reviewer agent definition.

Mode-aware focus sections must exist for every close mode the close
skills can pass via the `## Mode` prompt section. Adding a 4th close
mode (`story` for /xp-story-close) requires both updating the mode
list in Step 1 and adding a `### story` focus section. Centralizing
the assertions here means future close modes only need one test edit.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_AGENT_MD = _PLUGIN_ROOT / "agents" / "xp-close-reviewer.md"


class TestCloseReviewerAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _AGENT_MD.read_text()

    def test_agent_file_exists(self):
        self.assertTrue(_AGENT_MD.is_file(), f"agent missing: {_AGENT_MD}")

    def test_agent_is_read_only(self):
        # Agent must not be allowed to mutate state — Edit/Write absent
        # from frontmatter tools list.
        frontmatter = self.text.split("---", 2)[1]
        self.assertNotIn("Edit", frontmatter)
        self.assertNotIn("Write", frontmatter)

    def test_records_concerns_via_append_sh(self):
        # Concerns + blocks must be filed BEFORE prose so an aborted
        # merge doesn't lose them. Pinned across two append.sh blocks:
        # one for Block (severity high), one for Concern (severity
        # medium). Mirrors the xp-plan-reviewer record-then-prose
        # pattern. The DOTALL+lazy regex permits the multi-line
        # template between --type and --severity.
        body = self.text.split("---", 2)[2]
        self.assertRegex(
            body,
            re.compile(r'--type\s+"concern".*?--severity\s+"high"', re.DOTALL),
            "agent must include a Block append.sh template "
            '(--type "concern" + --severity "high")',
        )
        self.assertRegex(
            body,
            re.compile(r'--type\s+"concern".*?--severity\s+"medium"', re.DOTALL),
            "agent must include a Concern append.sh template "
            '(--type "concern" + --severity "medium")',
        )
        # --files attaches paths for the STRUCTURAL commit-auto-link.
        self.assertIn("--files", body)
        # Recording-before-prose ordering: two distinct phrasings so a
        # single ambiguous sentence elsewhere can't satisfy both.
        self.assertRegex(
            body,
            r"[Bb]efore\*{0,2}\s+returning the prose summary",
            "agent must explicitly state recording happens before prose",
        )
        self.assertRegex(
            body,
            r"(?i)do not emit.*prose",
            "agent must explicitly forbid emitting prose before recording",
        )


class TestModeFocusSections(unittest.TestCase):
    """Each close mode the close skills pass must have a ### <mode>
    focus section. Catches a regression where someone adds a new mode
    to the close-skill rotation but forgets the agent-side focus.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _AGENT_MD.read_text()

    def _assert_mode_section(self, mode: str) -> None:
        self.assertRegex(
            self.text,
            rf"###\s+{mode}\b",
            f"xp-close-reviewer must declare a {mode}-mode focus section",
        )

    def test_sprint_mode_focus_section(self):
        self._assert_mode_section("sprint")

    def test_plan_mode_focus_section(self):
        self._assert_mode_section("plan")

    def test_free_mode_focus_section(self):
        self._assert_mode_section("free")

    def test_story_mode_focus_section(self):
        self._assert_mode_section("story")

    def test_step1_lists_all_modes(self):
        # Step 1 enumerates the modes the agent accepts. The list must
        # include every mode that has a focus section, otherwise a
        # close skill passing that mode triggers the "missing input"
        # bail-out in the agent.
        step1_match = re.search(r"## Step 1.*?## Step 2", self.text, re.DOTALL)
        assert step1_match is not None, "Step 1 not found"
        step1 = step1_match.group(0)
        for mode in ("sprint", "plan", "free", "story"):
            self.assertIn(mode, step1, f"Step 1 mode list missing {mode!r}")

    def test_files_required_when_locatable(self):
        # The recording-instructions block must require --files for any
        # concern that names a concrete source path. The previous wording
        # was advisory ("when your bullet cites concrete paths") which let
        # the agent silently omit --files and disable the structural
        # auto-link probe — Resolves-Event trailers then never fired on
        # follow-up commits. Pin the strengthened wording so it can't
        # regress without a deliberate test edit.
        self.assertIn("MUST", self.text, "files-required wording lost the MUST")
        # The new instruction must mention --files in the same paragraph
        # as the requirement so the rule is actionable.
        files_paragraph = re.search(
            r"\*\*`?--files`? discipline.*?(?=\n\n|\n##)", self.text, re.DOTALL
        )
        assert files_paragraph is not None, "files-discipline paragraph missing"
        self.assertIn("MUST", files_paragraph.group(0))

    def test_resolves_event_handoff_in_prose(self):
        # The prose summary returned to the close skill must surface
        # event IDs alongside Concern/Block bullets so the orchestrator
        # can populate the next commit's `Resolves-Event:` trailer
        # without a second probe round-trip.
        self.assertIn("Resolves-Event", self.text)
        self.assertIn("event_id", self.text.lower() + " " + self.text)


if __name__ == "__main__":
    unittest.main()
