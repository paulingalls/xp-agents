#!/usr/bin/env python3
"""Prose-assertion test for xp-plan-reviewer tier-recommendation section.

Pins the §Tier Recommendation subsection of
plugins/xp-agents/agents/xp-plan-reviewer.md.

Code↔spec link (one-directional, per feedback_declarative_skill_prose): this
file is the canonical pin for the Tier Recommendation section. The agent prose
stays declarative and does NOT point back at this test path.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import tier_wire
from conftest import _PLUGIN_ROOT, _split_frontmatter_body

_PLAN_REVIEWER_MD = _PLUGIN_ROOT / "agents" / "xp-plan-reviewer.md"

_TIER_HEADING = "Tier Recommendation"

# Language-specific tokens and plugin-internal surface names that must NOT
# appear in the tier rubric — the rubric must work for any-language projects.
_FORBIDDEN_VOCAB = (
    ".py",
    ".ts",
    ".js",
    ".go",
    ".rs",
    "def ",
    "class ",
    "function ",
    " LOC",
    "lines of code",
    "ACCEPT_IN_FLIGHT",
    "close_cycle_stop_gate",
    "simplify_done",
    "assign-pending",
    "review_cycle_done",
)


class TestPlanReviewerTierRubric(unittest.TestCase):
    """Tier-recommendation section is complete and project-agnostic."""

    @classmethod
    def setUpClass(cls):
        raw = _PLAN_REVIEWER_MD.read_text()
        _, cls.body = _split_frontmatter_body(raw)
        # Slice from the Tier Recommendation heading to the next "### " heading
        # (or EOF), so assertions are scoped to the relevant section.
        start = cls.body.find(_TIER_HEADING)
        if start == -1:
            cls.tier_section = ""
        else:
            heading_start = cls.body.rfind("\n###", 0, start)
            if heading_start == -1:
                heading_start = 0
            after = cls.body.find("\n### ", heading_start + 4)
            cls.tier_section = (
                cls.body[heading_start:]
                if after == -1
                else cls.body[heading_start:after]
            )

    def test_tier_recommendation_section_exists(self):
        self.assertIn(
            _TIER_HEADING,
            self.body,
            "xp-plan-reviewer.md must contain a 'Tier Recommendation' section",
        )

    def test_all_recommended_tiers_present(self):
        """Every recommended_model value (in-agent + each model tier, incl.
        fable) must appear in the rubric — bound to tier_wire so a new tier
        can't be added to the vocabulary without a rubric row here."""
        for tier in tier_wire.RECOMMENDED_MODELS:
            self.assertIn(
                tier,
                self.tier_section,
                f"Tier recommendation section must document tier '{tier}'",
            )

    def test_topic_pattern_documented(self):
        self.assertIn(
            tier_wire.TIER_RECOMMENDATION_TOPIC_PREFIX,
            self.tier_section,
            "Tier recommendation section must document the event topic pattern "
            "'tier-recommendation-<story-id>'",
        )

    def test_recommended_model_metadata_key_documented(self):
        self.assertIn(
            "recommended_model",
            self.tier_section,
            "Tier recommendation section must document the 'recommended_model' "
            "metadata key",
        )

    def test_retract_when_ambiguous_rule_present(self):
        """Ambiguity emits a retraction (recommended_model null) so a stale
        earlier recommendation can't win the reverse-scan (debt d5697631a002)."""
        self.assertIn(
            "RETRACT",
            self.tier_section,
            "Tier recommendation section must document the RETRACT-WHEN-AMBIGUOUS rule",
        )
        self.assertIn("retracted", self.tier_section)

    def test_rubric_is_project_agnostic(self):
        for token in _FORBIDDEN_VOCAB:
            self.assertNotIn(
                token,
                self.tier_section,
                f"Tier recommendation rubric must not contain language-specific or "
                f"plugin-internal token: {token!r}",
            )

    def test_recommended_effort_metadata_key_documented(self):
        """The effort dimension (story-003) writes metadata.recommended_effort
        on the same tier-recommendation event — the contract consumed by
        /xp-assign (story-004)."""
        self.assertIn(
            "recommended_effort",
            self.tier_section,
            "Tier recommendation section must document the 'recommended_effort' "
            "metadata key",
        )

    def test_all_effort_levels_present(self):
        """Every effort level must appear in the rubric — bound to tier_wire so
        a new level can't enter the vocabulary without a rubric update (mirrors
        test_all_recommended_tiers_present)."""
        for effort in tier_wire.TEAMMATE_EFFORTS:
            self.assertIn(
                effort,
                self.tier_section,
                f"Tier recommendation section must document effort level '{effort}'",
            )

    def test_effort_scoped_as_claude_code_knob(self):
        """Effort is a Claude-Code reasoning knob — the rubric must scope it
        explicitly as such (AC3), not leave it as a bare provider-agnostic
        term."""
        self.assertIn(
            "Claude Code",
            self.tier_section,
            "Tier recommendation section must scope effort explicitly as a "
            "Claude Code knob",
        )

    def test_haiku_tier_gates_out_effort(self):
        """The binary tier-gate (story-001): a haiku-tier story never gets a
        recommended effort — the cheapest tier rejects the knob."""
        self.assertIn(
            "haiku",
            self.tier_section,
            "Tier recommendation section must name haiku in the effort tier-gate",
        )
        # Gate prose must instruct NOT emitting effort for the low tier(s).
        lowered = self.tier_section.lower()
        self.assertTrue(
            ("no recommended_effort" in lowered)
            or ("no recommended effort" in lowered)
            or ("not emit" in lowered and "effort" in lowered),
            "Tier recommendation section must instruct that haiku/in-agent "
            "stories emit no recommended_effort",
        )


if __name__ == "__main__":
    unittest.main()
