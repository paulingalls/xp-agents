#!/usr/bin/env python3
"""Pin: sprint-review must rerun verify-bearing acceptance and surface the matrix.

Milestone 6 (execution_plan.json §M6): /xp-sprint-review reruns every
verify-bearing acceptance item across the sprint (via verify_acceptance.py
--sprint, the story-001 primitive) grouped by surface, surfaces the per-surface
PASS/FAIL matrix to the user, and emits the deterministic sprint-verify event
the close gate consumes.

These pins keep the instruction in the agent/skill BODY (visible to the LLM at
review time) — not the frontmatter, where an `assertIn` on the full file text
would false-pass on a `description` mention the agent never reads. Mirrors
test_plan_reviewer_pin.py.
"""

import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_AGENT_PATH = Path(__file__).parent.parent.parent / "agents" / "xp-sprint-reviewer.md"
_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-sprint-review" / "SKILL.md"
)


class TestSprintReviewerVerifyPin(unittest.TestCase):
    """xp-sprint-reviewer.md body MUST direct a sprint-wide verify rerun."""

    @classmethod
    def setUpClass(cls):
        cls.frontmatter, cls.body = _split_frontmatter_body(_AGENT_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_agent_file_exists(self):
        self.assertTrue(_AGENT_PATH.is_file(), f"missing agent file: {_AGENT_PATH}")

    def test_body_directs_sprint_batch_verify(self):
        # Pin both the script and the --sprint flag so the rerun instruction
        # can't be trimmed to a vague "check acceptance" without a mechanism.
        self.assertIn(
            "verify_acceptance.py",
            self.body,
            "xp-sprint-reviewer body must direct running verify_acceptance.py "
            "to rerun the sprint's verify-bearing acceptance items",
        )
        self.assertIn(
            "--sprint",
            self.body,
            "xp-sprint-reviewer body must name the --sprint batch mode "
            "(story-001's primitive), not the per-story --story mode",
        )

    def test_body_directs_per_surface_matrix(self):
        # The result must be rendered grouped by surface — pin both tokens so
        # a phrasing tweak that drops the surface grouping fails the pin.
        self.assertIn(
            "matrix",
            self.body_lower,
            "xp-sprint-reviewer body must render the batch-verify results as a matrix",
        )
        self.assertIn(
            "surface",
            self.body_lower,
            "xp-sprint-reviewer body must group the matrix by surface",
        )

    def test_body_directs_surfacing_matrix_in_report(self):
        # The forked subagent's tool result is invisible to the user, so the
        # matrix must be carried in the returned report.
        self.assertIn(
            "report",
            self.body_lower,
            "xp-sprint-reviewer body must direct surfacing the matrix in its "
            "returned report (the subagent tool result is invisible)",
        )


class TestSprintReviewSkillVerifyPin(unittest.TestCase):
    """xp-sprint-review/SKILL.md body MUST direct the --sprint rerun before close."""

    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_skill_file_exists(self):
        self.assertTrue(_SKILL_PATH.is_file(), f"missing skill file: {_SKILL_PATH}")

    def test_body_names_sprint_mode_and_matrix(self):
        self.assertIn(
            "--sprint",
            self.body,
            "xp-sprint-review SKILL.md must name the --sprint batch verify mode",
        )
        self.assertIn(
            "matrix",
            self.body_lower,
            "xp-sprint-review SKILL.md must direct surfacing the per-surface "
            "matrix to the user",
        )

    def test_body_directs_verify_before_close(self):
        # The rerun must happen BEFORE the close dispatch, so the close gate
        # has a fresh verify event to read.
        self.assertIn(
            "before",
            self.body_lower,
            "xp-sprint-review SKILL.md must direct the verify rerun BEFORE "
            "invoking /xp-sprint-close",
        )
        self.assertIn(
            "/xp-sprint-close",
            self.body,
            "xp-sprint-review SKILL.md must name /xp-sprint-close as the step "
            "the verify rerun precedes",
        )


if __name__ == "__main__":
    unittest.main()
