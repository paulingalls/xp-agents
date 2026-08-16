#!/usr/bin/env python3
"""Conversion pin for the three formerly-forked skills (story-013).

`xp-review-plan`, `xp-sprint-review` and `xp-system-context` are converting
from `context: fork` to the inline-spawns-subagent pattern `xp-quality-review`
already ships, because injection cannot cross a fork boundary (story-001's
measurement, `docs/completed/PRELOAD_DELIVERY_MECHANISM.md`). This suite pins
the routing consequence first (increment 1, below); the conversion-shape
classes land alongside the SKILL.md edits themselves (increment 2), so this
file never carries a class asserting a frontmatter change ahead of the
frontmatter that makes it true.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import review_cycle_done

_CONVERTED_SKILLS = ("xp-review-plan", "xp-sprint-review", "xp-system-context")

_SUBAGENT_BY_SKILL = {
    "xp-review-plan": "xp-plan-reviewer",
    "xp-sprint-review": "xp-sprint-reviewer",
    "xp-system-context": "xp-system-analyzer",
}


class TestRoutingNoLongerMatchesPlanReview(unittest.TestCase):
    """Increment 1: xp-review-plan's Skill-tool return is LAUNCH once inline,
    so it must not route to a canonical target the way the forked skill's
    completion-timed return used to."""

    def test_xp_review_plan_is_absent_from_target_by_name(self):
        self.assertNotIn("xp-review-plan", review_cycle_done._TARGET_BY_NAME)

    def test_xp_review_plan_detects_to_none(self):
        self.assertIsNone(review_cycle_done._detect_target("xp-review-plan"))
        self.assertIsNone(review_cycle_done._detect_target("xp-agents:xp-review-plan"))


if __name__ == "__main__":
    unittest.main()
