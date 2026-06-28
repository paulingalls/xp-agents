#!/usr/bin/env python3
"""xp-quality-review SKILL.md + preload.sh routing pins for sprint-104 story-003.

The risk-gated single-spawn pipeline:
  Step 1   — gather reviewer inputs (concerns, debts, findings) — NO spawn here
  Step 1.4 — spawn xp-risk-classifier ONCE on MODE=self-find; SKIP on consume-findings
  Step 1.5 — build the SINGLE xp-code-reviewer prompt; on RISK=high prepend a
             `## Review Focus` block; spawn EXACTLY ONE reviewer. Anti-fan-out.

The 7th test is the load-bearing structural guard: the single Agent() call to
xp-code-reviewer must live inside Step 1.5 — NOT before Step 1.4 — else the
Review Focus enrichment lands after the reviewer has already returned (the
plan-reviewer-caught ordering bug from concern d4909886f51c).

Sprint-103 lesson: 3-spawn fan-out had irreducible coordination races; the
single-spawn invariant is the redesign that fixes it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _md_helpers import _split_frontmatter_body
from conftest import _PLUGIN_ROOT

_SKILL_PATH = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"
_PRELOAD_PATH = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"


def _section_slice(body: str, start: str, end: str) -> str:
    """Slice between two headings (start inclusive, end exclusive); raise loud."""
    s = body.find(start)
    e = body.find(end, s + 1 if s != -1 else 0)
    if s == -1 or e == -1:
        raise AssertionError(
            f"Could not locate section bounds: start={start!r} found={s != -1}, "
            f"end={end!r} found={e != -1}"
        )
    return body[s:e]


class TestQualityReviewRiskRouting(unittest.TestCase):
    """Pin the Step 1.4 / Step 1.5 risk-gated single-spawn pipeline."""

    @classmethod
    def setUpClass(cls):
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = _split_frontmatter_body(text)
        cls.lower = cls.body.lower()
        cls.preload = _PRELOAD_PATH.read_text(encoding="utf-8")

    def test_step_1_4_classifier_spawn_mode_gated_on_self_find(self):
        """Step 1.4 spawns xp-risk-classifier exactly once on MODE=self-find."""
        self.assertIn("## Step 1.4", self.body, "SKILL.md must have a Step 1.4")
        section = _section_slice(self.body, "## Step 1.4", "## Step 1.5")
        section_lower = section.lower()
        self.assertIn(
            "xp-risk-classifier",
            section,
            "Step 1.4 must name the xp-risk-classifier subagent",
        )
        self.assertIn(
            "self-find",
            section_lower,
            "Step 1.4 must gate the spawn on MODE=self-find",
        )
        self.assertRegex(
            section_lower,
            r"first[\s-]line",
            "Step 1.4 must describe the strict first-line RISK= parse",
        )

    def test_step_1_4_skips_on_consume_findings(self):
        """Step 1.4 explicitly SKIPs on MODE=consume-findings.

        Sprint-103 lesson: close /code-review already ran; the extra
        classifier call is wasted on the close path.
        """
        section = _section_slice(self.body, "## Step 1.4", "## Step 1.5")
        section_lower = section.lower()
        self.assertRegex(
            section_lower,
            r"consume-findings[^.]{0,80}skip|skip[^.]{0,80}consume-findings",
            "Step 1.4 must explicitly SKIP on MODE=consume-findings",
        )

    def test_step_1_5_emits_review_focus_block_on_risk_high(self):
        """Step 1.5 emits the verbatim ## Review Focus block on RISK=high."""
        self.assertIn("## Step 1.5", self.body, "SKILL.md must have a Step 1.5")
        section = _section_slice(self.body, "## Step 1.5", "## Step 2:")
        self.assertIn(
            "RISK=high",
            section,
            "Step 1.5 must name RISK=high as the enrichment trigger",
        )
        # Verbatim — interface contract with story-001's xp-code-reviewer
        # Section 1c (which recognizes the same literal string).
        self.assertIn(
            "## Review Focus",
            section,
            "Step 1.5 must name the ## Review Focus block verbatim",
        )

    def test_step_1_5_single_spawn_invariant_anti_fan_out(self):
        """Step 1.5 declares the single-spawn invariant with anti-fan-out prose.

        Sprint-103's 3-spawn parallel fan-out had irreducible coordination
        races (filesystem, SMM appends, dedupe-key fragility); single-spawn
        enriched avoids all of them.
        """
        section = _section_slice(self.body, "## Step 1.5", "## Step 2:")
        section_lower = section.lower()
        # Positive: exactly-one language.
        self.assertRegex(
            section_lower,
            r"single[\s-]spawn|exactly one|one\s+xp-code-reviewer",
            "Step 1.5 must declare the single-spawn invariant",
        )
        # Negative: explicit anti-fan-out guard.
        self.assertRegex(
            section_lower,
            r"\bnot\b[^.]{0,100}(fan[\s-]?out|multi[\s-]?spawn|multiple\s+spawn)",
            "Step 1.5 must explicitly guard against fan-out / multi-spawn",
        )

    def test_xp_code_reviewer_spawn_lives_in_step_1_5_only(self):
        """STRUCTURAL guard for plan-reviewer concern d4909886f51c.

        The single Agent() call to xp-code-reviewer MUST live inside the
        Step 1.5 slice. If it lives in Step 1 (the pre-1.4 region), the
        Review Focus enrichment is chronologically impossible — Step 1
        returns before Step 1.4 even runs.
        """
        step_1_to_1_4 = _section_slice(self.body, "## Step 1:", "## Step 1.4")
        step_1_5 = _section_slice(self.body, "## Step 1.5", "## Step 2:")
        # The spawn must be inside Step 1.5 (the prompt-build + spawn site).
        self.assertIn(
            "xp-code-reviewer",
            step_1_5,
            "Step 1.5 must contain the xp-code-reviewer spawn (post-enrichment)",
        )
        # The spawn must NOT have already happened in Step 1.
        self.assertNotIn(
            "Agent(",
            step_1_to_1_4,
            "Step 1 (pre-1.4) must NOT spawn the reviewer — "
            "Step 1.5 owns the spawn so the Review Focus block can be appended first",
        )

    def test_preload_emits_changed_files_block(self):
        """preload.sh emits a `## Changed Files` block — input to the classifier."""
        self.assertIn(
            "## Changed Files",
            self.preload,
            "preload.sh must emit a ## Changed Files block",
        )

    def test_preload_emits_close_diff_unavailable_flag(self):
        """preload.sh emits a deterministic CLOSE_DIFF_UNAVAILABLE=true flag.

        The existing `## Close diff unavailable` prose block is for humans;
        the flag is the machine-detectable signal that disambiguates an
        unresolvable close range from a clean tree (a parser otherwise
        cannot tell which silent case applied).
        """
        self.assertRegex(
            self.preload,
            r"CLOSE_DIFF_UNAVAILABLE\s*=\s*true",
            "preload.sh must emit a deterministic CLOSE_DIFF_UNAVAILABLE=true flag",
        )


if __name__ == "__main__":
    unittest.main()
