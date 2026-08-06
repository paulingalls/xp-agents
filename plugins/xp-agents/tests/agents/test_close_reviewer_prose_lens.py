#!/usr/bin/env python3
"""Prose Hygiene pins for xp-close-reviewer.md, plus cross-file parity.

story-002 promotes prose hygiene (the four-bucket comment rule) to a named
review dimension in BOTH reviewers. Only a module reading both agent files
can prove the rule is worded identically, so the parity assertion lives
here rather than being split across the two per-agent suites.

Each reviewer numbers the section in its OWN scheme — xp-code-reviewer.md
runs 1..5, xp-close-reviewer.md runs Step 1..Step 4 — so the heading is
per-file and parity covers the rule BODY, which is what must not drift.

Four-bucket rule: A (restates code) and B (narrates removed history) ->
delete, git holds history. C (checkable claim) -> convert to a test. D (a
why the code cannot express) -> exempt, never flagged. Plus: a comment
block >=25 lines is a simplification smell in the CODE, not prose to trim.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _md_helpers import _slice, _split_frontmatter_body, assert_project_agnostic
from conftest import _PLUGIN_ROOT

_CODE_REVIEWER_MD = _PLUGIN_ROOT / "agents" / "xp-code-reviewer.md"
_CLOSE_REVIEWER_MD = _PLUGIN_ROOT / "agents" / "xp-close-reviewer.md"

_CODE_REVIEWER_HEADING = "## 5. Prose Hygiene"
_CLOSE_REVIEWER_HEADING = "## Step 3b: Prose Hygiene"


def _prose_hygiene_section(body: str, heading: str, end_marker: str) -> str:
    return _slice(body, heading, (end_marker,))


class TestCloseReviewerProseHygiene(unittest.TestCase):
    """Pin xp-close-reviewer.md's Prose Hygiene section."""

    @classmethod
    def setUpClass(cls):
        text = _CLOSE_REVIEWER_MD.read_text(encoding="utf-8")
        _, cls.body = _split_frontmatter_body(text)
        cls.section = _prose_hygiene_section(
            cls.body, _CLOSE_REVIEWER_HEADING, "## Mode-Specific Focus"
        )
        cls.lower = cls.section.lower()

    def test_heading_is_named_not_buried(self):
        self.assertIn(
            _CLOSE_REVIEWER_HEADING, self.body, "prose hygiene must be a named heading"
        )

    def test_buckets_a_and_b_fix_is_delete_not_reword(self):
        self.assertIn("restates the code", self.lower)
        self.assertIn("narrates removed history", self.lower)
        self.assertIn("delete", self.lower)
        self.assertNotIn("reword", self.lower)

    def test_bucket_c_fix_is_convert_to_a_test(self):
        self.assertIn("checkable claim", self.lower)
        self.assertIn("convert to a test", self.lower)

    def test_bucket_d_is_an_explicit_exemption(self):
        self.assertIn("exempt", self.lower)
        self.assertIn("why the code cannot express", self.lower)
        for instance in (
            "rejected-design rationale",
            "external constraints",
            "machine-checked markers",
        ):
            self.assertIn(instance, self.lower)

    def test_25_line_block_routes_to_code_simplification(self):
        self.assertIn("25", self.section)
        self.assertIn("simplification smell", self.lower)
        self.assertIn("comment block", self.lower)

    def test_section_is_project_agnostic(self):
        assert_project_agnostic(self, self.section, "close-reviewer prose hygiene")


class TestProseHygieneParity(unittest.TestCase):
    """The rule body must be byte-identical across both reviewer agents."""

    def test_section_is_identical_in_both_agents(self):
        code_reviewer_text = _CODE_REVIEWER_MD.read_text(encoding="utf-8")
        close_reviewer_text = _CLOSE_REVIEWER_MD.read_text(encoding="utf-8")
        _, code_reviewer_body = _split_frontmatter_body(code_reviewer_text)
        _, close_reviewer_body = _split_frontmatter_body(close_reviewer_text)

        code_reviewer_section = _prose_hygiene_section(
            code_reviewer_body, _CODE_REVIEWER_HEADING, "## Recording Findings"
        )
        close_reviewer_section = _prose_hygiene_section(
            close_reviewer_body, _CLOSE_REVIEWER_HEADING, "## Mode-Specific Focus"
        )
        self.assertEqual(
            code_reviewer_section,
            close_reviewer_section,
            "the prose-hygiene rule must be worded identically in both "
            "reviewer agents — a single shared rule, not two drifting copies. "
            "`_slice` excludes the heading, so each file keeps its own "
            "section numbering; everything below the heading must match",
        )


if __name__ == "__main__":
    unittest.main()
