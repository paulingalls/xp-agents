#!/usr/bin/env python3
"""Conversion pin for the three formerly-forked skills (story-013).

`xp-review-plan`, `xp-sprint-review` and `xp-system-context` are converting
from `context: fork` to the inline-spawns-subagent pattern `xp-quality-review`
already ships, because injection cannot cross a fork boundary (story-001's
measurement, `docs/completed/PRELOAD_DELIVERY_MECHANISM.md`). `TestRouting...`
below pins the routing consequence (increment 1, landed already).

The conversion-shape classes land ONE PER SKILL, in the same commit as that
skill's own SKILL.md edit — not as a single class loping over all three. The
commit gate runs the full suite on every commit (see CLAUDE.md), so a shared
loop asserting a frontmatter change ahead of two of the three frontmatters
would leave every commit red until the last skill converts. Per-skill classes
let each of the three land its own green commit, per the story's own
"three small commits, not one" instruction.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import review_cycle_done
from conftest import _PLUGIN_ROOT, _split_frontmatter_body


class TestRoutingNoLongerMatchesPlanReview(unittest.TestCase):
    """Increment 1: xp-review-plan's Skill-tool return is LAUNCH once inline,
    so it must not route to a canonical target the way the forked skill's
    completion-timed return used to."""

    def test_xp_review_plan_is_absent_from_target_by_name(self):
        self.assertNotIn("xp-review-plan", review_cycle_done._TARGET_BY_NAME)

    def test_xp_review_plan_detects_to_none(self):
        self.assertIsNone(review_cycle_done._detect_target("xp-review-plan"))
        self.assertIsNone(review_cycle_done._detect_target("xp-agents:xp-review-plan"))


def _frontmatter_and_body(name: str) -> tuple[str, str]:
    text = (_PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text()
    return _split_frontmatter_body(text)


def _assert_converted(testcase: unittest.TestCase, name: str, subagent: str) -> None:
    """AC1/AC2/AC4, shared by every per-skill conversion class below.

    AC4: no internal fork declared. AC1: Agent tool present, subagent
    spawned by name. AC2: a do-not-do-this-yourself clause survives — the
    isolation the fork gave for free, now the caller's own discipline.
    """
    frontmatter, body = _frontmatter_and_body(name)
    testcase.assertNotIn("context: fork", frontmatter, f"{name} still declares a fork")
    testcase.assertIn("Agent", frontmatter, f"{name} allowed-tools must include Agent")
    spawned = re.findall(r'subagent_type:\s*"([^"]+)"', body)
    testcase.assertTrue(spawned, f"{name} SKILL.md must declare a subagent_type")
    testcase.assertTrue(
        any(subagent in s for s in spawned),
        f"{name} must spawn {subagent}, found {spawned}",
    )
    testcase.assertIn(
        "do not do this",
        body.lower(),
        f"{name} must keep a do-not-absorb-the-subagent's-work clause",
    )


class TestSystemContextConverted(unittest.TestCase):
    def test_converted(self):
        _assert_converted(self, "xp-system-context", "xp-system-analyzer")


class TestSprintReviewConverted(unittest.TestCase):
    def test_converted(self):
        _assert_converted(self, "xp-sprint-review", "xp-sprint-reviewer")


if __name__ == "__main__":
    unittest.main()
