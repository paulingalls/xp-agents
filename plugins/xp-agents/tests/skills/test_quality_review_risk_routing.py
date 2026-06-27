#!/usr/bin/env python3
"""Content guard for /xp-quality-review's risk-gated escalation block (story-002).

SKILL.md is markdown; we cannot test the LLM follows its prose. This is a
shape-only guard: the risk-routing section exists, names the RISK=high
trigger, declares the parallel 3-spawn shape, the dedupe step, and the
hard cap. Accidental removal or rewording that drops one of those
elements fails this test.

Why bounded at 3 spawns: the close-skill's /code-review workflow owns
the unbounded multi-agent path; per-increment must not duplicate it.
See SMM decision a56a99eb7846 (risk-escalation-shape).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from conftest import _PLUGIN_ROOT

_SKILL_MD = _PLUGIN_ROOT / "skills" / "xp-quality-review" / "SKILL.md"


class TestQualityReviewRiskRouting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = _SKILL_MD.read_text()

    def test_skill_md_exists(self):
        self.assertTrue(_SKILL_MD.exists(), f"missing: {_SKILL_MD}")

    def test_risk_high_trigger_named(self):
        self.assertIn("RISK=high", self.body)

    def test_parallel_fan_out_declared(self):
        # Both 'parallel' and the explicit spawn count must appear so the
        # LLM cannot collapse the routing to a single sequential pass.
        self.assertIn("parallel", self.body.lower())
        self.assertIn("3", self.body)

    def test_dedupe_step_named(self):
        self.assertTrue(
            "dedupe" in self.body.lower() or "dedup" in self.body.lower(),
            "risk-routing block must require deduping findings before acting",
        )

    def test_spawn_cap_enforced(self):
        # The cap protects the per-increment budget; without it the routing
        # could justify unbounded fan-out and duplicate /code-review's role.
        self.assertIn("Never escalate beyond 3 spawns", self.body)

    def test_three_angles_named(self):
        # The angle prompts are what give the fan-out its multi-angle value;
        # collapsing all three to the same generalist pass defeats the design.
        lower = self.body.lower()
        self.assertIn("state-lifecycle", lower)
        self.assertIn("concurrency", lower)
        self.assertIn("decision-path", lower)


if __name__ == "__main__":
    unittest.main()
