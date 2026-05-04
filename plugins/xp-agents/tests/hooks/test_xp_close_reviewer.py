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
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from event_schema import EVENT_TYPE_CONCERN

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_AGENT_MD = _PLUGIN_ROOT / "agents" / "xp-close-reviewer.md"
_AGENT_TEXT = _AGENT_MD.read_text()


class TestCloseReviewerHasNoTier3(unittest.TestCase):
    """xp-close-reviewer must not contain Tier 3 / Step 3.5 prose.

    M-8 sprint-055 / story-005: security review migrated out of the
    close-reviewer agent (Step 3.5 / Tier 3) into the close skills'
    Step 4.5 (free/sprint/plan). The reviewer is now quality-only.
    Pin the absence so the migrated prose cannot silently re-emerge.
    """

    @classmethod
    def setUpClass(cls):
        # Split frontmatter from body so frontmatter-only assertions
        # (tools list) and body-only assertions (prose) don't cross-
        # contaminate. The .md is `---\nfrontmatter\n---\nbody`.
        parts = _AGENT_TEXT.split("---\n", 2)
        cls.frontmatter = parts[1] if len(parts) >= 2 else ""
        cls.body = parts[2] if len(parts) >= 3 else _AGENT_TEXT

    def test_body_has_no_tier_3_or_step_3_5_or_security_review(self):
        for needle in ("Tier 3", "Step 3.5", "security-review"):
            with self.subTest(needle=needle):
                self.assertNotIn(
                    needle,
                    self.body,
                    f"xp-close-reviewer body must not reference {needle!r} "
                    "(security migrated to close-skill Step 4.5 in M-8)",
                )

    def test_body_has_no_skill_invocation(self):
        # `Skill(` calls in the BODY would mean the reviewer still
        # invokes a Skill tool. Frontmatter is split off above so this
        # checks only the prose, not the tools list.
        self.assertNotIn(
            "Skill(",
            self.body,
            "xp-close-reviewer body must not invoke Skill(...) — "
            "security review fires from the close skill, not the reviewer",
        )

    def test_frontmatter_tools_omits_skill(self):
        # YAML-aware match: the tools list is a `tools:` key. Skill
        # appearing as a value (after a `-` or comma in `tools:`)
        # must be absent. We allow the literal substring "Skill" to
        # appear inside YAML keys that aren't `tools:` (none today,
        # but defensive). Regex anchors on `tools:` followed by lines
        # with `- Skill` or `- "Skill"`.
        self.assertNotRegex(
            self.frontmatter,
            r"(?m)^\s*tools:[^\n]*?\bSkill\b|^\s*-\s*Skill\s*$",
            "xp-close-reviewer frontmatter tools list must not include "
            "Skill (no Skill invocations remain in body after Step 3.5 "
            "deletion)",
        )


class TestCloseReviewerAgent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _AGENT_TEXT

    def test_agent_file_exists(self):
        self.assertTrue(_AGENT_MD.is_file(), f"agent missing: {_AGENT_MD}")

    def test_agent_is_read_only(self):
        # Agent must not be allowed to mutate state — Edit/Write absent
        # from frontmatter tools list.
        frontmatter = self.text.split("---", 2)[1]
        self.assertNotIn("Edit", frontmatter)
        self.assertNotIn("Write", frontmatter)

    def test_metadata_template_includes_close_cycle_id(self):
        # Critical: without close_cycle_id in the metadata template,
        # severity=high quality Blocks recorded by the reviewer fall
        # outside the shared Step 6 count-concerns query (which filters
        # by --cycle-id). The Block bullet would be invisible to the
        # abort-default flag — silently undermining the M-8 promise that
        # "deterministic count covers both quality and security blocks".
        # The sprint-close reviewer caught this at sprint-055; this pin
        # prevents recurrence.
        body = self.text.split("---", 2)[2]
        self.assertIn(
            "close_cycle_id",
            body,
            "xp-close-reviewer metadata template must include "
            "close_cycle_id so the shared Step 6 abort-default's "
            "count-concerns --cycle-id query picks up severity=high "
            "quality Blocks. Without it, quality Blocks silently drop.",
        )
        self.assertIn(
            "## Close Cycle ID",
            body,
            "Step 1 must read '## Close Cycle ID' from the invoking "
            "prompt — the close skills inject it as a top-level prompt "
            "section so the reviewer can substitute it into metadata.",
        )

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
            re.compile(
                rf'--type\s+"{EVENT_TYPE_CONCERN}".*?--severity\s+"high"', re.DOTALL
            ),
            "agent must include a Block append.sh template "
            f'(--type "{EVENT_TYPE_CONCERN}" + --severity "high")',
        )
        self.assertRegex(
            body,
            re.compile(
                rf'--type\s+"{EVENT_TYPE_CONCERN}".*?--severity\s+"medium"', re.DOTALL
            ),
            "agent must include a Concern append.sh template "
            f'(--type "{EVENT_TYPE_CONCERN}" + --severity "medium")',
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
        cls.text = _AGENT_TEXT

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

    def test_plan_mode_security_posture_bullet_removed(self):
        # The plan-mode focus list must not mention security posture.
        # Per M-8: security review fires from the close skill's Step 4.5
        # (sprint/plan/free), not from the close-reviewer agent — the
        # reviewer is quality-only.
        self.assertNotIn(
            "Security posture of the cumulative diff",
            self.text,
            "The plan-mode 'Security posture of the cumulative diff' "
            "bullet must be removed — security review is the close "
            "skill's Step 4.5, not the reviewer's responsibility.",
        )


if __name__ == "__main__":
    unittest.main()
