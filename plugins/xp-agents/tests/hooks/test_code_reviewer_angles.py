#!/usr/bin/env python3
"""Pin: xp-code-reviewer body must carry the state/lifecycle angle + self-verify.

Sprint-103 story-001 (Milestone 1 — per-increment review floor) adds two prompt
directives the single per-increment reviewer must carry, in-agent, with no
sub-agent fan-out:

1. **A dedicated state/lifecycle/concurrency correctness angle.** The v3.11.1
   close caught two confirmed regressions the cheap self-find pass missed — a
   stop gate that latches off forever and an accept marker that never drains.
   The reviewer must hunt that failure class explicitly: trace each state
   field's lifecycle (who sets it, who clears it, is every set reachable-cleared
   on every path), latch/drain/one-way-transition bugs.

2. **A bounded adversarial self-verify pass.** Before fixing/recording, the
   reviewer makes ONE in-agent refute pass over its own candidate findings,
   defaulting to refuted on uncertainty — but sparing correctness/state-lifecycle
   candidates that have a plausible failure path (those are exactly the
   milestone's target class; an over-aggressive refute would re-introduce the
   false-negative it exists to kill). The refute kills nitpicks, not real
   state-machine findings.

Pinning these in the BODY (not frontmatter) ensures the agent prompt itself
carries the directives at review time. Synonym SETS (not exact strings) keep
phrasing tweaks valid while a missing directive still fails.
"""

import re
import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_AGENT_PATH = Path(__file__).parent.parent.parent / "agents" / "xp-code-reviewer.md"


class TestCodeReviewerAngles(unittest.TestCase):
    """xp-code-reviewer.md body MUST carry the state/lifecycle angle + self-verify."""

    @classmethod
    def setUpClass(cls):
        cls.frontmatter, cls.body = _split_frontmatter_body(_AGENT_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_body_carries_state_lifecycle_angle(self):
        # The dedicated angle must name the lifecycle framing AND a concrete
        # failure-class token (latch / drain) so a stray "state" elsewhere can't
        # false-pass. Require both within one ~400-char window — the angle bullet.
        self.assertIn(
            "lifecycle",
            self.body_lower,
            "xp-code-reviewer body must add a dedicated state/lifecycle review "
            "angle — 'lifecycle' framing not found",
        )
        co_located = re.search(
            r"lifecycle.{0,400}(latch|drain)|(latch|drain).{0,400}lifecycle",
            self.body_lower,
            re.DOTALL,
        )
        self.assertIsNotNone(
            co_located,
            "the state/lifecycle angle must name a concrete failure class "
            "(latch / drain) near the lifecycle framing — the gap that missed "
            "the two v3.11.1 regressions",
        )

    def test_body_directs_tracing_state_field_lifecycle(self):
        # The angle is only actionable if it tells the reviewer HOW: trace who
        # sets and who clears each state field, on every path. Pin set+clear.
        self.assertTrue(
            ("set" in self.body_lower and "clear" in self.body_lower),
            "the state/lifecycle angle must direct tracing each state field's "
            "set AND clear (is every set reachable-cleared on every path) — "
            "'set'/'clear' framing not found",
        )

    def test_body_carries_bounded_self_verify_pass(self):
        # A refute/self-verify pass over the reviewer's own candidate findings.
        verify_tokens = ("self-verify", "refute", "refut")
        self.assertTrue(
            any(token in self.body_lower for token in verify_tokens),
            "xp-code-reviewer body must add a bounded self-verify (refute) pass "
            f"over its candidate findings — none of {verify_tokens} found",
        )
        # Co-locate the refute with its target (candidate / finding) so it reads
        # as a directive, not a stray mention.
        co_located = re.search(
            r"refut\w*.{0,240}(candidate|finding)|(candidate|finding).{0,240}refut",
            self.body_lower,
            re.DOTALL,
        )
        self.assertIsNotNone(
            co_located,
            "the self-verify pass must target the reviewer's own candidate "
            "findings (co-locate 'refute' with 'candidate'/'finding')",
        )

    def test_self_verify_defaults_to_refuted_on_uncertainty(self):
        # The bias that kills false positives: default to refuted when the
        # failure path can't be substantiated.
        co_located = re.search(
            r"refut\w*.{0,200}(uncertain|substantiat|default)"
            r"|(uncertain|substantiat|default).{0,200}refut",
            self.body_lower,
            re.DOTALL,
        )
        self.assertIsNotNone(
            co_located,
            "the self-verify pass must default to refuted on uncertainty / when "
            "a failure path cannot be substantiated",
        )

    def test_self_verify_spares_plausible_state_findings(self):
        # TENSION GUARD (plan-review assumption bb4c7631811d): Change 1 finds
        # MORE state-machine bugs; Change 2 drops unsubstantiated ones. An
        # over-aggressive refute would kill a TRUE latch/drain finding — exactly
        # the false-negative class this milestone exists to remove. The prose
        # must spare candidates with a plausible failure path and kill only
        # nitpicks. Pin a softener so a future tightening trips this test.
        spare_tokens = ("plausible", "nitpick", "spare", "real failure", "genuine")
        self.assertTrue(
            any(token in self.body_lower for token in spare_tokens),
            "the self-verify pass must SPARE findings with a plausible failure "
            "path (kill nitpicks, not true state-machine findings) — none of "
            f"{spare_tokens} found; an unguarded refute re-introduces the "
            "false-negative this milestone removes",
        )

    def test_self_verify_stays_in_agent_no_fan_out(self):
        # Story constraint: the self-verify is in-agent reasoning only — no
        # sub-agent fan-out (that is story-002's risk-gated escalation). Pin it
        # so a future tightening to real sub-agents trips this test and forces a
        # revisit of the per-increment budget bound.
        no_fanout_tokens = (
            "no sub-agent",
            "no subagent",
            "in-agent",
            "no fan-out",
            "without fanning",
        )
        self.assertTrue(
            any(token in self.body_lower for token in no_fanout_tokens),
            "the self-verify pass must stay in-agent with no sub-agent fan-out "
            f"(per-increment budget bound) — none of {no_fanout_tokens} found",
        )


if __name__ == "__main__":
    unittest.main()
