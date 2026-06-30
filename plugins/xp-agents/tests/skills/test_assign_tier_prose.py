#!/usr/bin/env python3
"""Pin: xp-assign SKILL.md documents the Layer-3 execution-shape decision.

story-003. /xp-assign is the universal per-story execution-shape decision: it
reads the session default tier (TEAMMATE_DEFAULT) plus the plan-reviewer's
per-story recommendation (RECOMMENDED_TIER) and applies a six-branch behavior
table. It may exit in-agent without spawning, is valid for solo too, and
audits divergent picks via a tier_override event.

The frontmatter must carry the tools the new branches need (the override-event
write + the divergence question). The prose must state the in-agent-never-an-
executor_model invariant (resolves event b1c3c28967f2) and the tier_override
contract (metadata.action=tier_override, read by the override-audit story).
"""

import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "xp-assign" / "SKILL.md"


def _slice(body: str, start_marker: str, end_markers: tuple[str, ...]) -> str:
    """Return the body region from start_marker up to the first end_marker."""
    start = body.index(start_marker)
    rest = body[start + len(start_marker) :]
    ends = [rest.index(m) for m in end_markers if m in rest]
    return rest[: min(ends)] if ends else rest


class TestAssignTierProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frontmatter, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        # The Layer-3 decision lives in its own step; slice it for the
        # vocabulary checks so bash blocks in unrelated steps don't pollute.
        cls.decision = _slice(
            cls.body,
            "## Step 0: Execution-shape decision",
            ("## Step 1",),
        )

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    # --- Frontmatter: the new branches need tools the old frontmatter lacked
    # (plan-review concern b03e4ed92982) ----------------------------------
    def test_allowed_tools_permits_override_event_write(self):
        """The tier_override audit event is written via append.sh."""
        self.assertIn("append.sh", self.frontmatter)

    def test_allowed_tools_permits_divergence_question(self):
        """The divergence branch asks exactly one AskUserQuestion."""
        self.assertIn("AskUserQuestion", self.frontmatter)

    # --- All six branches of the behavior table, evaluated in order -------
    def test_disable_branch_documented(self):
        """1. default off → exit with a hint at the kickoff teammate-support
        setting; no spawn."""
        self.assertRegex(self.decision, r"(?i)\boff\b")
        self.assertRegex(self.decision, r"(?i)teammate.support")

    def test_in_agent_flag_branch_documented(self):
        """2. --in-agent flag forces in-agent regardless of recommendation."""
        self.assertIn("--in-agent", self.decision)

    def test_in_agent_recommendation_branch_documented(self):
        """3. recommendation in-agent → continue here, no spawn."""
        self.assertRegex(self.decision, r"(?i)continue")
        self.assertRegex(self.decision, r"(?i)in-agent")

    def test_match_default_silent_spawn_branch_documented(self):
        """4. recommendation matches default tier → silent spawn at that tier."""
        self.assertRegex(self.decision, r"(?i)silent")

    def test_divergence_branch_documented(self):
        """5. recommendation diverges from default → exactly one question."""
        self.assertIn("AskUserQuestion", self.decision)
        self.assertRegex(self.decision, r"(?i)diverge")

    def test_no_recommendation_branch_documented(self):
        """6. no recommendation (none) → apply default; inherit → no model flag."""
        self.assertRegex(self.decision, r"(?i)\bnone\b")
        self.assertRegex(self.decision, r"(?i)inherit")

    # --- Invariants and contracts ----------------------------------------
    def test_in_agent_never_written_to_executor_model(self):
        """Resolves b1c3c28967f2: in-agent is a control-flow signal, never a
        value written to executor_model. The prose must state this explicitly."""
        self.assertRegex(
            self.decision,
            r"(?is)in-agent\b.{0,120}\bnever\b.{0,40}executor_model"
            r"|never\b.{0,60}\bin-agent\b.{0,60}executor_model",
        )

    def test_executor_model_only_valid_tiers_or_null(self):
        """Spawning paths set executor_model only to a valid tier or leave it
        null (inherit)."""
        self.assertRegex(self.decision, r"(?i)haiku")
        self.assertRegex(self.decision, r"(?i)sonnet")
        self.assertRegex(self.decision, r"(?i)opus")

    def test_tier_override_event_rule_documented(self):
        """The override audit event carries metadata.action=tier_override."""
        self.assertIn("tier_override", self.decision)
        self.assertRegex(self.decision, r"(?i)action.{0,6}tier_override")

    def test_single_spawn_invariant_preserved(self):
        """The spawning branches still spawn exactly ONE teammate per
        invocation."""
        self.assertRegex(self.body, r"(?i)one teammate|single.spawn|exactly one")

    def test_universal_framing_in_description(self):
        """The Description/intro frames the skill as the universal per-story
        execution-shape decision (may exit without spawning; valid for solo)."""
        self.assertRegex(self.body, r"(?i)execution.shape")

    # --- Project-agnostic vocabulary (CLAUDE.md guardrail) ----------------
    def test_no_language_specific_tokens_in_decision_prose(self):
        """Tier is chosen by complexity, not language — the decision prose must
        not lean on language names or language-tool words."""
        lowered = self.decision.lower()
        for tok in (
            "javascript",
            "typescript",
            "golang",
            "regex",
            "language-specific",
            "pytest",
        ):
            self.assertNotIn(tok, lowered, f"language-specific token leaked: {tok!r}")

    def test_no_internal_marker_surface_names_as_rule(self):
        """Plugin-internal marker constant names must not appear as the rule in
        shipped prose."""
        for tok in (
            "ASSIGN_PENDING",
            "ACCEPT_IN_FLIGHT",
            "PLAN_AWAITING_REVIEW",
            ".assign-pending",
        ):
            self.assertNotIn(tok, self.body, f"internal surface name leaked: {tok!r}")


if __name__ == "__main__":
    unittest.main()
