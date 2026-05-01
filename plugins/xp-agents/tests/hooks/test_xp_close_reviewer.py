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
_AGENT_TEXT = _AGENT_MD.read_text()


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

    def test_skill_in_tools_frontmatter(self):
        # M-3 Tier 3 step (## Step 3.5) invokes Skill(skill: "security-review", ...).
        # The Claude Code agent runtime denies the call if Skill is missing
        # from the frontmatter tools list — the prose contract is mute
        # without the capability grant.
        frontmatter = self.text.split("---", 2)[1]
        self.assertRegex(
            frontmatter,
            r"tools:[^\n]*\bSkill\b",
            "agent must list Skill in frontmatter tools so Step 3.5 can "
            'invoke Skill(skill: "security-review", ...)',
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
        # The prior plan-mode "Security posture of the cumulative diff"
        # bullet is now covered cross-mode by Step 3.5 (M-3). Keeping
        # both would duplicate the contract — one prose-only mention vs
        # one cross-mode Skill dispatch.
        self.assertNotIn(
            "Security posture of the cumulative diff",
            self.text,
            "The plan-mode 'Security posture of the cumulative diff' "
            "bullet must be removed — Step 3.5 (M-3) now dispatches "
            "/security-review cross-mode, so the prose-only bullet is "
            "redundant.",
        )


class TestStep35Tier3SecurityReview(unittest.TestCase):
    """SKILL.md must define the M-3 Tier 3 security-review step.

    Milestone M-3 of the security review tiered migration adds a Tier 3
    cumulative-diff /security-review step to xp-close-reviewer for
    sprint, plan, and free close modes. The enforcement is a prose
    contract in the agent definition (the LLM judges /security-review's
    prose findings); these assertions pin the contract so a future edit
    can't silently drop or weaken it.

    Severity convention (Constraints d57963f81ac1, xp-accept Step 1c):
    Block=high, Concern=medium. Block findings must default the merge
    confirmation to Abort (per milestone M-3 done state).
    """

    _H_3 = "## Step 3:"
    _H_3_5 = "## Step 3.5:"
    _H_3_5_FULL = "## Step 3.5: Tier 3 Security Review"
    _H_4 = "## Step 4:"

    @classmethod
    def setUpClass(cls):
        cls.text = _AGENT_TEXT
        cls.pos_3 = cls.text.find(cls._H_3)
        cls.pos_3_5 = cls.text.find(cls._H_3_5)
        cls.pos_4 = cls.text.find(cls._H_4)
        cls.section_3_5 = cls.text[cls.pos_3_5 : cls.pos_4] if cls.pos_3_5 != -1 else ""
        cls.section_3_5_lower = cls.section_3_5.lower()

    def test_step_3_5_section_exists(self):
        self.assertIn(
            self._H_3_5_FULL,
            self.text,
            "xp-close-reviewer must define a Step 3.5 Tier 3 Security "
            "Review section (M-3). Without this heading, the tiered "
            "migration is not in place at the close gate.",
        )

    def test_step_3_5_between_step_3_and_step_4(self):
        self.assertGreater(self.pos_3, -1, "Step 3 heading must exist")
        self.assertGreater(self.pos_3_5, -1, "Step 3.5 heading must exist")
        self.assertGreater(self.pos_4, -1, "Step 4 heading must exist")
        self.assertLess(
            self.pos_3,
            self.pos_3_5,
            "Step 3.5 must appear AFTER Step 3 (Analyze runs first)",
        )
        self.assertLess(
            self.pos_3_5,
            self.pos_4,
            "Step 3.5 must appear BEFORE Step 4 (Tier 3 dispatches "
            "before recording so findings flow into the same recording "
            "pipeline)",
        )

    def test_step_3_5_dispatches_security_review(self):
        self.assertRegex(
            self.section_3_5,
            r'Skill\(\s*skill\s*:\s*"security-review"',
            'Step 3.5 must invoke Skill(skill: "security-review", ...) '
            "to fire Tier 3 (M-3 contract).",
        )

    def test_step_3_5_names_all_three_close_modes(self):
        # Anchor on the section only — modes appear elsewhere in the
        # agent (Mode-Specific Focus). Pin that Step 3.5's prose itself
        # names sprint/plan/free so the LLM cannot silently scope the
        # dispatch to one mode.
        for mode in ("sprint", "plan", "free"):
            self.assertIn(
                mode,
                self.section_3_5_lower,
                f"Step 3.5 must name {mode!r} so the LLM dispatches "
                "Tier 3 in that mode (cross-mode contract per M-3).",
            )

    def test_step_3_5_excludes_story_mode(self):
        # Story-close skips Tier 3 because Tier 2 at /xp-accept already
        # reviewed the story diff before story-close fired. The prose
        # must say so explicitly — otherwise the LLM may dispatch Tier 3
        # redundantly on story-mode close, doubling work on the same
        # diff. Bidirectional regex tolerates either order
        # ("NOT story mode" or "story mode is intentionally not run").
        self.assertIn(
            "story",
            self.section_3_5_lower,
            "Step 3.5 must mention story mode (to declare exclusion).",
        )
        self.assertRegex(
            self.section_3_5,
            r"(?is)("
            r"\b(not|skip|exclude|except)\b.{0,80}\bstory\b"
            r"|\bstory\b.{0,80}\b(not|skip|exclude|except)\b"
            r")",
            "Step 3.5 must explicitly exclude story mode "
            "(NOT/skip/exclude/except in either order around 'story') "
            "so the LLM cannot silently dispatch redundantly.",
        )

    def test_step_3_5_block_defaults_to_abort(self):
        # Per execution_plan.json M-3 done state: "Block defaults merge
        # to Abort". Pin the relationship (Block ↔ Abort within ~200
        # chars), not just both words appearing somewhere — "Block"
        # appears throughout the section and an unrelated co-occurrence
        # would falsely satisfy a substring check.
        self.assertRegex(
            self.section_3_5,
            r"(?is)(block.{0,200}abort|abort.{0,200}block)",
            "Step 3.5 must pin Block→Abort relationship (within ~200 "
            "chars) per milestone M-3 done state. Two unrelated "
            "occurrences of the words don't prove the contract.",
        )

    def test_step_3_5_block_records_severity_high(self):
        # Per Constraints d57963f81ac1 + xp-accept Step 1c convention:
        # Block=high. Recording medium silently downgrades a
        # consciously-shipped Block in the event log.
        self.assertRegex(
            self.section_3_5,
            r'(?is)block.{0,400}--severity\s+["\']?high',
            "Step 3.5 Block path must record --severity high (NOT medium). "
            "Per Constraints d57963f81ac1 (Block=high); downgrading hides "
            "a consciously-shipped Block in the event log.",
        )

    def test_step_3_5_concern_records_severity_medium(self):
        self.assertRegex(
            self.section_3_5,
            r'(?is)concern.{0,400}--severity\s+["\']?medium',
            "Step 3.5 Concern path must record --severity medium per "
            "the Block=high/Concern=medium convention.",
        )

    def test_step_3_5_scope_is_cumulative_diff(self):
        # Mirrors xp-accept Step 1c: the args string MUST name the
        # scope so the LLM does not silently scope to a single commit.
        self.assertIn(
            "cumulative",
            self.section_3_5_lower,
            "Step 3.5 args string must name 'cumulative' diff scope "
            "so the security-review skill scopes to the full close diff "
            "(mirrors xp-accept Step 1c convention).",
        )


if __name__ == "__main__":
    unittest.main()
