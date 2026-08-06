#!/usr/bin/env python3
"""Pins for the /xp-schedule SKILL.md (story-002, the decide-half).

xp-schedule consumes the ready-frontier preload vars, asks solo/parallel only
on a >=2 disjoint frontier (auto-solo otherwise), promotes the chosen frontier
scheduled->in-progress, and sets each story's execution_mode. These pins keep
the skill's authoring prose honest about that contract.
"""

import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-schedule" / "SKILL.md"
)


class TestScheduleSkillProse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_PATH.read_text()
        cls.frontmatter, cls.body = _split_frontmatter_body(cls.text)

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_frontmatter_names_xp_schedule(self):
        self.assertIn("name: xp-schedule", self.frontmatter)

    def test_is_inline_not_forked(self):
        # Interactive (AskUserQuestion) → inline; auto-discovery suites enforce
        # the Sequential-discipline pin only on inline skills.
        self.assertNotIn("context: fork", self.frontmatter)

    def test_self_wires_preload(self):
        self.assertIn("scripts/preload.sh", self.body)

    def test_has_sequential_discipline_pin(self):
        self.assertIn("Sequential discipline", self.body)

    def test_consumes_frontier_vars(self):
        self.assertIn("FRONTIER_COUNT", self.body)
        self.assertIn("PARALLELIZABLE", self.body)

    def test_consumes_overlap_vars(self):
        # The preload emits three unprovable/collision signals; the skill must
        # name all three, or the branch it forgets is a false PARALLELIZABLE
        # the agent reports as "no reason given".
        self.assertIn("OVERLAP_DETAIL", self.body)
        self.assertIn("GLOB_FORCED", self.body)
        self.assertIn("UNSCOPED_IDS", self.body)

    def test_reports_downgrade_reason_instead_of_silent_solo(self):
        # Story-004: the auto-solo branch must direct the agent to report why
        # it downgraded rather than pick solo silently.
        self.assertIn("report why instead of downgrading silently", self.body)

    def test_asks_solo_or_parallel(self):
        self.assertIn("AskUserQuestion", self.body)

    def test_sets_execution_mode(self):
        self.assertIn("execution_mode", self.body)

    def test_promotes_to_in_progress(self):
        self.assertIn("in-progress", self.body)

    def test_parallel_handoff_names_per_story_pipeline(self):
        # Story-001: /xp-schedule's parallel-mode tail must point the lead at
        # per-story plan→review→spawn (the M2 pipeline), not the legacy single
        # batch plan. The full phrase is distinctive enough to detect drift.
        self.assertIn("per-story plan→review→spawn", self.body)

    def test_parallel_handoff_drops_legacy_batch_plan_phrase(self):
        # Negative guard: the old tail message ("plan the batch") explicitly
        # instructed a single batch plan; the M2 reshape removes that flow.
        self.assertNotIn("plan the batch", self.body)

    def test_parallel_handoff_drops_legacy_splits_spawns_phrase(self):
        # Negative guard: the old tail also said "/xp-assign splits + spawns".
        # /xp-assign reshapes to per-story spawn in story-003; the tail must
        # stop advertising the split-N-ways shape now.
        self.assertNotIn("splits + spawns", self.body)


if __name__ == "__main__":
    unittest.main()
