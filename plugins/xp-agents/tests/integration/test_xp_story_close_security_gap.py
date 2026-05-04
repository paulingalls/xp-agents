#!/usr/bin/env python3
"""Step 4.5 (Security Review) is conditionally wired into xp-story-close.

Story-001 sprint-058: closes concern 0763b3041fc9. Story-close historically
skipped Step 4.5 with a blanket exclusion on the assumption that
sprint-close's cumulative diff would always wrap it. That assumption fails
for orphan story branches and for story-close runs without an active sprint
— the cumulative `/security-review` never fires, leaving only commit-time
deterministic scans.

These tests pin the conditional wiring:
  - The `_Step4_5SecurityIncludeTests` mixin guarantees the standard Step 4.5
    contract (heading position, substitution placeholders, append.sh
    metadata shape, clean-separation from the close-reviewer prompt).
  - The negative-pin tests below assert the prior blanket skip prose is
    gone and the conditional clause references the sprint_exists /
    orphan-detection mechanisms a future editor must preserve.

Negative-pin convention (constraint b769cb0cabaa): split SKILL.md into
frontmatter + body before grepping. The frontmatter's `name:` field
contains `xp-story-close`; without splitting, an `assertNotIn` against
the full text could false-pass when the body's blanket-skip phrase is
re-introduced under a slightly different wording that overlaps the
frontmatter literal.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _close_fixtures import _Step4_5SecurityIncludeTests
from conftest import _IntegrationTestCase

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-story-close" / "SKILL.md"
_SHARED_MD = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"


def _split_frontmatter_body(text: str) -> tuple[str, str]:
    """Split a SKILL.md into (frontmatter, body) on the closing `---` fence.

    Mirrors tests/scaffold/_helpers.py::frontmatter_body but reproduced
    here to avoid a cross-package import (scaffold/ is a separate test
    suite with its own conftest path setup).
    """
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), match.group(2)


class TestStoryCloseStep4_5(_Step4_5SecurityIncludeTests, _IntegrationTestCase):
    """Story-close inherits the standard Step 4.5 contract.

    The mixin's assertions (heading present, between Step 4 and Steps 5/6,
    substitutions named, close-reviewer prompt clean of `security`,
    append.sh emits kind=security at high/medium severity) all apply to
    the conditional wiring just the same — gating the block on a shell
    `if` does not change its prose contract.
    """

    _SKILL_MD = _SKILL_MD
    _MODE = "story"
    _SKILL_NAME = "xp-story-close"


class TestStoryCloseStep4_5Conditional(unittest.TestCase):
    """Story-close-specific assertions: conditional clause + blanket-skip removal."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.text = _SKILL_MD.read_text()
        cls.frontmatter, cls.body = _split_frontmatter_body(cls.text)

    def test_conditional_references_sprint_exists(self):
        # The conditional must reference the `sprint_cli.py exists` check
        # (sprint_exists()) so a future editor can see WHICH primitive
        # gates Step 4.5. Substring on `sprint_cli.py exists` pins the CLI
        # invocation — prose alone (`sprint exists`) would let a refactor
        # drop the check silently.
        self.assertIn(
            "sprint_cli.py",
            self.body,
            "conditional Step 4.5 must invoke sprint_cli.py to determine "
            "whether a sprint envelope wraps this story-close",
        )
        # Tolerant of bash line continuation (`\` + newline) — the
        # `sprint_cli.py exists` invocation naturally splits across lines
        # to keep each line within the 80-col SKILL.md width budget.
        self.assertRegex(
            self.body,
            r"sprint_cli\.py\b[\s\S]{0,120}?\bexists\b",
            "conditional Step 4.5 must use sprint_cli.py exists as the "
            "sprint_exists primitive",
        )

    def test_conditional_references_orphan_detection(self):
        # The orphan-branch arm must invoke branching.py list-story-orphans
        # — that's the canonical primitive (branch_queries.list_orphan_
        # story_branches) for "story branch not referenced by an active
        # sprint story". Prose like "orphan branch" alone would let a
        # future editor drop the actual check.
        self.assertIn(
            "list-story-orphans",
            self.body,
            "conditional Step 4.5 must invoke branching.py list-story-orphans "
            "to detect orphan story branches (the second sprint_exists=False "
            "case the original concern named)",
        )

    def test_blanket_skip_addendum_removed(self):
        # The prior "Story-close addendum to Step 6 (security exclusion)"
        # asserted Step 4.5 NEVER fires from story-close. With the
        # conditional in place, that addendum directly contradicts the
        # new behavior — it must be removed wholesale, not just edited.
        # Negative-pin against the body so a frontmatter line referencing
        # `xp-story-close` cannot false-pass the absence check.
        body_lower = self.body.lower()
        self.assertNotIn(
            "security exclusion",
            body_lower,
            "blanket 'security exclusion' addendum must be removed — "
            "Step 4.5 now fires conditionally from story-close",
        )
        self.assertNotIn(
            "story-close does not run",
            body_lower,
            "blanket 'story-close does not run /security-review' must be "
            "removed — replaced by the conditional Step 4.5",
        )

    def test_step_4_5_section_appears_with_conditional_marker(self):
        # The Step 4.5 section in story-close must be marked as conditional
        # — a future reader skimming the headings should see immediately
        # that this is NOT the unconditional invocation that free/sprint/
        # plan-close use. A literal "Conditional" / "conditional" marker
        # near the Step 4.5 heading is the structural signal.
        step_4_5_idx = self.body.find("Step 4.5")
        self.assertGreater(step_4_5_idx, -1, "Step 4.5 reference must exist in body")
        # Look at the heading line itself (up to the next newline).
        eol = self.body.find("\n", step_4_5_idx)
        heading_line = (
            self.body[step_4_5_idx:eol] if eol > -1 else self.body[step_4_5_idx:]
        )
        self.assertRegex(
            heading_line,
            r"(?i)conditional",
            "Step 4.5 heading in story-close must mark the section as "
            "Conditional so a reader sees the gating immediately",
        )


class TestSharedPipelineScopingLine(unittest.TestCase):
    """Shared `_close_pipeline_shared.md` 'Skills that apply this step'
    line names story-close (with the conditional qualifier) so a reader
    consulting the shared doc sees all four close skills can fire Step 4.5.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.shared_text = _SHARED_MD.read_text()

    def test_scoping_line_includes_story_with_conditional_qualifier(self):
        # The line currently reads:
        #   Skills that apply this step: **free, sprint, plan** close
        #   (story-close skips ...)
        # Post-story-001 it must include `story` in the bolded list (or
        # a sibling phrase) AND name the gating qualifier "no sprint
        # envelope" (or equivalent prose) so the reader sees WHEN
        # story-close fires Step 4.5.
        scope_line_match = re.search(
            r"Skills that apply this step:[^\n]*", self.shared_text
        )
        assert scope_line_match is not None, (
            "shared file must keep the 'Skills that apply this step:' line"
        )
        scope_line = scope_line_match.group(0)
        self.assertIn(
            "story",
            scope_line.lower(),
            "scoping line must name story-close alongside free/sprint/plan "
            "(post-story-001 conditional invocation)",
        )
        self.assertRegex(
            scope_line.lower(),
            r"(no\s+sprint\s+envelope|when\s+no\s+sprint|orphan)",
            "scoping line must name the gating condition (no sprint "
            "envelope wraps / orphan branch) so a reader sees WHEN "
            "story-close applies Step 4.5",
        )

    def test_scoping_line_drops_blanket_story_skips(self):
        # The prior "(story-close skips — sprint-close's cumulative diff
        # already covers each story)" parenthetical contradicts the new
        # conditional behavior. It must be removed or rewritten so it no
        # longer reads as an unconditional skip.
        self.assertNotRegex(
            self.shared_text,
            r"story-close\s+skips\b",
            "blanket 'story-close skips' phrasing must be removed — "
            "story-close now applies Step 4.5 conditionally",
        )


if __name__ == "__main__":
    unittest.main()
