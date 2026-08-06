#!/usr/bin/env python3
"""xp-quality-review SKILL.md + preload.sh spawn-structure pins (sprint-113 story-002).

story-002 removed the xp-risk-classifier from the self-find path. The reviewer
(xp-code-reviewer §1c) now self-triages risk from the diff + its injected
Constraints pillar, so the two-spawn (classifier -> reviewer) sequence collapses
to ONE unconditional xp-code-reviewer spawn:

  Step 1 — gather reviewer inputs (concerns, debts, findings) — NO spawn here
  Step 2 — build the SINGLE xp-code-reviewer prompt and spawn EXACTLY ONE
           reviewer, unconditionally. No classifier, no RISK gate, no
           ## Review Focus enrichment. Anti-fan-out invariant preserved.

These tests pin the removal: no Step 1.4, no classifier reference, no
Review-Focus/RISK/SIGNALS plumbing anywhere in the skill, and no redundant
preload ## Design Context block (the reviewer gets Constraints via SubagentStart
injection — decision recorded sprint-113). The single-spawn invariant from
sprint-103 (3-spawn fan-out had irreducible coordination races) still holds.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _md_helpers import _split_frontmatter_body
from conftest import _PLUGIN_ROOT

_SKILL_PATH = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"
_PRELOAD_PATH = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "scripts" / "preload.sh"
_AGENT_PATH = _PLUGIN_ROOT / "agents" / "xp-code-reviewer.md"

# Both sides of the spawn contract state how many review areas there are.
_AGENT_AREA_COUNT_RE = re.compile(r"work through all (\w+) areas", re.IGNORECASE)
_SKILL_AREA_COUNT_RE = re.compile(r"review all (\w+) areas", re.IGNORECASE)


class TestQualityReviewSpawnStructure(unittest.TestCase):
    """Pin the collapsed single-unconditional-spawn structure (no classifier)."""

    @classmethod
    def setUpClass(cls):
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = _split_frontmatter_body(text)
        cls.lower = cls.body.lower()
        cls.preload = _PRELOAD_PATH.read_text(encoding="utf-8")

    # --- Classifier removal ------------------------------------------------

    def test_no_risk_classifier_step_or_reference(self):
        """The classifier is gone: no Step 1.4, no xp-risk-classifier anywhere."""
        self.assertNotIn(
            "## Step 1.4",
            self.body,
            "Step 1.4 (classifier spawn) must be removed",
        )
        self.assertNotIn(
            "xp-risk-classifier",
            self.body,
            "SKILL.md must not reference the deleted xp-risk-classifier agent",
        )

    def test_no_review_focus_or_risk_enrichment_plumbing(self):
        """No RISK gate, no ## Review Focus block, no SIGNALS parsing survive."""
        self.assertNotIn(
            "## Review Focus",
            self.body,
            "The classifier-fed ## Review Focus enrichment must be gone — "
            "the reviewer self-triages",
        )
        self.assertNotIn(
            "RISK=high",
            self.body,
            "No RISK=high branch — the reviewer spawn is unconditional",
        )
        self.assertNotIn(
            "SIGNALS",
            self.body,
            "No SIGNALS= parsing — that was classifier plumbing",
        )

    # --- Single unconditional reviewer spawn -------------------------------

    def test_exactly_one_agent_spawn(self):
        """Exactly one Agent() spawn remains — the reviewer. The classifier
        Agent() call is gone, so a second spawn would be a regression."""
        self.assertEqual(
            self.body.count("Agent("),
            1,
            "SKILL.md must contain exactly ONE Agent() spawn (the reviewer); "
            "the classifier spawn was removed",
        )

    def test_reviewer_spawn_present_and_single(self):
        """The one remaining spawn targets xp-code-reviewer, and the skill
        declares the single-spawn invariant with anti-fan-out prose."""
        self.assertIn(
            "xp-code-reviewer",
            self.body,
            "SKILL.md must spawn the xp-code-reviewer",
        )
        # Positive: exactly-one language.
        self.assertRegex(
            self.lower,
            r"single[\s-]spawn|exactly one|one\s+xp-code-reviewer",
            "SKILL.md must declare the single-spawn invariant",
        )
        # Negative: explicit anti-fan-out guard.
        self.assertRegex(
            self.lower,
            r"\bnot\b[^.]{0,100}(fan[\s-]?out|multi[\s-]?spawn|multiple\s+spawn)",
            "SKILL.md must explicitly guard against fan-out / multi-spawn",
        )

    def test_reviewer_spawn_is_unconditional(self):
        """No conditional gating of the reviewer spawn on a classifier result.

        The reviewer runs unconditionally in self-find mode; the only remaining
        mode branch (self-find vs consume-findings) selects the correctness
        handling, not whether the reviewer runs.
        """
        # No leftover "if Step 1.4" / "if the classifier" style gating.
        self.assertNotIn("Step 1.4", self.body)
        self.assertNotIn("classifier", self.lower)

    # --- preload.sh --------------------------------------------------------

    def test_preload_emits_changed_files_block(self):
        """preload.sh still emits a `## Changed Files` block (reviewer input)."""
        self.assertIn(
            "## Changed Files",
            self.preload,
            "preload.sh must emit a ## Changed Files block",
        )

    def test_preload_emits_close_diff_unavailable_flag(self):
        """preload.sh still emits the deterministic CLOSE_DIFF_UNAVAILABLE=true flag."""
        self.assertRegex(
            self.preload,
            r"CLOSE_DIFF_UNAVAILABLE\s*=\s*true",
            "preload.sh must emit a deterministic CLOSE_DIFF_UNAVAILABLE=true flag",
        )

    def test_preload_drops_redundant_design_context_block(self):
        """preload.sh no longer emits a `## Design Context` block.

        It was a second render of the Constraints pillar built solely for the
        classifier's prompt (the classifier had no SMM injection). The reviewer
        receives the Constraints pillar via SubagentStart `_inject_full` and
        §1c reads it directly, so the preload block is redundant and removed
        (decision recorded sprint-113 story-002).
        """
        self.assertNotIn(
            "## Design Context",
            self.preload,
            "preload.sh must not emit the redundant ## Design Context block",
        )
        # And the skill must not pass such a block to any spawn.
        self.assertNotIn(
            "## Design Context",
            self.body,
            "SKILL.md must not pass a ## Design Context block to the reviewer — "
            "it gets Constraints via injection",
        )


class TestSpawnPromptEnumeratesEveryReviewArea(unittest.TestCase):
    """Both sides of the spawn contract, pinned together.

    The task instruction in the spawn prompt is the concrete order the subagent
    follows; its definition's preamble is only background. An area added to the
    agent and not to this prompt is an area no review runs — a green gate over
    a lens that never fired. Pinning the agent alone cannot see that, so the
    count and the area names are asserted across BOTH files here.
    """

    @classmethod
    def setUpClass(cls):
        _, cls.skill_body = _split_frontmatter_body(
            _SKILL_PATH.read_text(encoding="utf-8")
        )
        cls.agent_text = _AGENT_PATH.read_text(encoding="utf-8")

    def test_area_count_matches_the_agent_preamble(self):
        agent_match = _AGENT_AREA_COUNT_RE.search(self.agent_text)
        skill_match = _SKILL_AREA_COUNT_RE.search(self.skill_body)
        self.assertIsNotNone(
            agent_match, "xp-code-reviewer.md must state how many areas it covers"
        )
        self.assertIsNotNone(
            skill_match, "the spawn prompt must tell the reviewer how many areas"
        )
        assert agent_match is not None and skill_match is not None
        self.assertEqual(
            skill_match.group(1).lower(),
            agent_match.group(1).lower(),
            "the spawn prompt and the agent definition disagree about how many "
            "review areas there are — the subagent follows the prompt, so the "
            "extra area silently never runs",
        )

    def test_spawn_prompt_names_each_area(self):
        lowered = self.skill_body.lower()
        for area in ("correctness", "drift", "debt", "reuse", "prose hygiene"):
            self.assertIn(
                area,
                lowered,
                f"the spawn prompt must name the {area!r} area — an unnamed "
                "area is one the subagent has no instruction to run",
            )


if __name__ == "__main__":
    unittest.main()
