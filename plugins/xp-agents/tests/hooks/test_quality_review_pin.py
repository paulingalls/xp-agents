#!/usr/bin/env python3
"""Pin: xp-quality-review Step 1 must read /code-review's JSON findings array.

/code-review is now identify-only: it returns a JSON array of correctness
findings and fixes nothing. The old handoff — where /code-review fixed some
findings and the orchestrator labeled each APPLIED or SKIPPED before passing
the skipped ones on — no longer happens. Pin the SKILL body so the
APPLIED/SKIPPED accountability framing cannot creep back, and so the
JSON-findings-array instruction stays present.

Also pin approach (A): because the subagent and orchestrator edit files
during the cycle, the orchestrator must re-run /code-review on the staged
diff before committing so the committed diff is independently scanned.
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
        # The orchestrator no longer reconstructs findings from conversation
        # memory; it reads the JSON array /code-review returns.
        self.assertIn(
            "json",
            self.body_lower,
            "xp-quality-review Step 1 must instruct reading /code-review's "
            "JSON findings array",
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

    def test_re_reviews_staged_diff_before_commit(self):
        # Approach (A): the subagent and orchestrator edit files during this
        # cycle — changes the opening /code-review never saw. The orchestrator
        # must re-run /code-review on the staged diff before committing so the
        # actual committed diff gets an independent correctness scan.
        co_located = re.search(
            r"re-run.{0,160}/code-review|/code-review.{0,160}before committing",
            self.body_lower,
            re.DOTALL,
        )
        self.assertIsNotNone(
            co_located,
            "xp-quality-review must instruct re-running /code-review on the "
            "staged diff before committing (approach A) — reviewer/orchestrator "
            "edits otherwise ship unreviewed",
        )


if __name__ == "__main__":
    unittest.main()
