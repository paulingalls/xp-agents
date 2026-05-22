#!/usr/bin/env python3
"""Pin: xp-quality-review Step 1 must read /code-review's JSON findings array.

/code-review is now identify-only: it returns a JSON array of correctness
findings and fixes nothing. The old handoff — where /code-review fixed some
findings and the orchestrator labeled each APPLIED or SKIPPED before passing
the skipped ones on — no longer happens. Pin the SKILL body so the
APPLIED/SKIPPED accountability framing cannot creep back, and so the
JSON-findings-array instruction stays present.
"""

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


if __name__ == "__main__":
    unittest.main()
