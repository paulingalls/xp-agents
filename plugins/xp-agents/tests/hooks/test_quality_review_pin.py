#!/usr/bin/env python3
"""Pin: xp-quality-review branches on MODE (consume-findings vs self-find).

Role lever: per-increment, no broad review runs, so the preload emits
MODE=self-find and the xp-code-reviewer self-finds correctness. At close, the
broad review ran first, the preload emits MODE=consume-findings, and Step 1
reads its findings (each entry fixed, never the dead APPLIED/SKIPPED
disposition). The old Step 4 (re-run the broad review on the staged diff) is
GONE — there is no per-increment one to re-run.

WHERE THOSE FINDINGS LIVE HAS NOW CHANGED TWICE, so the pin below asserts BOTH
channels rather than swinging between them a third time. Close Step 4b names a
primary and a fallback, and they do not return the same shape: the shipped
Workflow script hands back a structured `findings` array in its task
notification, while the `/code-review` fallback forks and returns prose. A skill
body describing only one sends the orchestrator looking for something that is
not there half the time, and the likeliest recovery is to reconstruct from
memory — the one thing this pin has always existed to prevent.
"""

import re
import unittest
from pathlib import Path

from conftest import _split_frontmatter_body

_SKILL_PATH = (
    Path(__file__).parent.parent.parent / "skills" / "xp-quality-review" / "SKILL.md"
)


class TestQualityReviewPin(unittest.TestCase):
    """xp-quality-review SKILL body must describe both findings channels."""

    @classmethod
    def setUpClass(cls):
        _, cls.body = _split_frontmatter_body(_SKILL_PATH.read_text())
        cls.body_lower = cls.body.lower()

    def test_step1_describes_both_findings_channels(self):
        """Consume-findings reads what the launcher that actually ran returned.

        Asserting only one channel is how this pin went wrong twice: it demanded
        an array while the launcher was a forked Skill returning prose, then
        demanded prose and forbade "findings array" outright — which the primary
        launcher now genuinely returns.
        """
        self.assertIn("findings` array", self.body)
        self.assertIn("prose", self.body_lower)

    def test_each_channel_is_attributed_to_its_launcher(self):
        """Naming both shapes is not enough — an orchestrator that cannot tell
        WHICH it is holding still guesses. Each must sit within reach of the
        launcher that produces it, so the reader can match what Step 4b did to
        what to read."""
        array_ctx = re.search(
            r"workflow.{0,400}findings` array",
            self.body,
            re.DOTALL | re.IGNORECASE,
        )
        self.assertIsNotNone(
            array_ctx,
            "the structured findings array must be attributed to the Workflow "
            "launcher that returns it",
        )
        prose_ctx = re.search(
            r"fallback.{0,400}prose",
            self.body_lower,
            re.DOTALL,
        )
        self.assertIsNotNone(
            prose_ctx,
            "the prose channel must be attributed to the fallback launcher "
            "that returns it",
        )

    def test_the_capped_summary_is_not_dropped_on_the_floor(self):
        """The array is not the whole result. The script reports what its
        verifier cap dropped, and a close that reads only the findings treats a
        truncated pass as a complete one — which is the exact failure the cap
        was built to make impossible to hide."""
        self.assertRegex(
            self.body_lower,
            r"cap",
            "Step 1 must tell the reader the summary says whether the review "
            "hit its cap",
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
