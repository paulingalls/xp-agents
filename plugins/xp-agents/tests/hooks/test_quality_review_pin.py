#!/usr/bin/env python3
"""Pin: xp-quality-review branches on MODE (consume-findings vs self-find).

Role lever: per-increment, /code-review does NOT run, so the preload emits
MODE=self-find and the xp-code-reviewer self-finds correctness. At close,
/code-review ran first, the preload emits MODE=consume-findings, and Step 1
reads /code-review's JSON findings array (each entry fixed, never the dead
APPLIED/SKIPPED disposition). The old Step 4 (re-run /code-review on the
staged diff) is GONE — there is no per-increment /code-review to re-run.
"""

import re
import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-quality-review" / "SKILL.md"
)


class TestQualityReviewPin(unittest.TestCase):
    """xp-quality-review SKILL body MUST read the JSON findings array."""

    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_step1_reads_json_findings_array(self):
        # In consume-findings mode the orchestrator reads the JSON array
        # /code-review returns (it does not reconstruct from memory).
        self.assertIn(
            "json",
            self.body_lower,
            "xp-quality-review consume-findings branch must instruct reading "
            "/code-review's JSON findings array",
        )

    def test_branches_on_mode(self):
        # The preload emits MODE; Step 1 must branch on both values.
        for token in ("consume-findings", "self-find"):
            self.assertIn(
                token,
                self.body_lower,
                f"xp-quality-review must branch on MODE — '{token}' missing",
            )

    def test_self_find_directs_reviewer_to_self_find(self):
        # In self-find mode the reviewer must be told to find correctness
        # itself (no /code-review ran). Pin the directive co-located with
        # 'correctness' so it reads as a real instruction.
        co_located = re.search(
            r"self-find.{0,200}correctness|correctness.{0,200}self-find",
            self.body_lower,
            re.DOTALL,
        )
        self.assertIsNotNone(
            co_located,
            "xp-quality-review self-find branch must direct the reviewer to "
            "find correctness itself",
        )

    def test_no_applied_skipped_labeling(self):
        # The APPLIED/SKIPPED disposition is dead — /code-review fixes nothing,
        # so every finding is unaddressed. The labeling must not reappear.
        for token in ("APPLIED", "SKIPPED"):
            self.assertNotIn(
                token,
                self.body,
                f"xp-quality-review must not carry the dead {token} "
                "disposition label — /code-review identifies, never fixes",
            )

    def test_no_code_review_rerun_step(self):
        # The old Step 4 (re-run /code-review on the staged diff before commit)
        # is gone: per-increment there is no /code-review to re-run. The
        # reviewer self-finds on the diff; Step 3 fixes are covered by tests.
        rerun = re.search(r"re-run.{0,40}/code-review", self.body_lower, re.DOTALL)
        self.assertIsNone(
            rerun,
            "xp-quality-review must not re-run /code-review — the per-increment "
            "workflow /code-review was removed (role lever)",
        )


if __name__ == "__main__":
    unittest.main()
