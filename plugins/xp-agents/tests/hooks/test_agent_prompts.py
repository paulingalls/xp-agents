#!/usr/bin/env python3
"""Tests for agent prompt content: purpose filters, aging references, directives.

Split from test_plugin_integrity.py for file size management.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import system_context_schema


class TestHousekeeperPurposeFilters(unittest.TestCase):
    """M5: housekeeper prompt has per-pillar purpose filters."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent.parent.parent / "agents" / "xp-housekeeper.md"
        cls.content = path.read_text()

    def test_intent_has_purpose_filter(self):
        self.assertIn("project-level", self.content.lower())

    def test_constraints_has_purpose_filter(self):
        self.assertIn("bind every", self.content.lower())

    def test_risks_has_purpose_filter(self):
        self.assertIn("systemic", self.content.lower())

    def test_wisdom_has_purpose_filter(self):
        self.assertIn("3 months", self.content.lower())

    def test_no_tactical_promotion_instruction(self):
        self.assertIn("work-selection triage", self.content.lower())

    def test_has_good_bad_examples(self):
        good_count = self.content.lower().count("good:")
        bad_count = self.content.lower().count("bad:")
        self.assertGreaterEqual(good_count, 4, "Need good example per pillar")
        self.assertGreaterEqual(bad_count, 4, "Need bad example per pillar")


class TestProcessGuideSystemContext(unittest.TestCase):
    """PROCESS_GUIDE.md's System Context section must surface the
    reversal-test discriminator so contributors learn the principle-vs-
    convention discipline without opening the analyzer prompt. Also
    pin the principle cap numbers and the retire-principle CLI mention
    so the guide stays in sync with the schema. All pins scope to the
    "### System Context" section — caps like "15" appear elsewhere in
    the guide (Constraints pillar), so a file-wide substring would
    false-green if the section dropped the principles-specific text.
    """

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent.parent.parent / "PROCESS_GUIDE.md"
        cls.content = path.read_text()
        anchor = "### System Context"
        start = cls.content.index(anchor)
        end = cls.content.index("###", start + len(anchor))
        cls.section = cls.content[start:end]

    def test_reversal_test_phrase_present(self):
        self.assertIn(
            "reversed, makes this a different project",
            self.section,
            "PROCESS_GUIDE.md §System Context must cite the reversal "
            "test so contributors learn the discriminator without "
            "opening the analyzer prompt",
        )

    def test_principles_caps_present(self):
        soft = system_context_schema.PRINCIPLES_SOFT_CAP
        hard = system_context_schema.PRINCIPLES_HARD_CAP
        for value in (str(soft), str(hard)):
            with self.subTest(cap=value):
                self.assertIn(
                    value,
                    self.section,
                    f"PROCESS_GUIDE.md §System Context must mention "
                    f"the principles cap value {value} so the guide "
                    "stays in sync with system_context_schema",
                )

    def test_retire_principle_cited(self):
        self.assertIn(
            "retire-principle",
            self.section,
            "PROCESS_GUIDE.md §System Context must cite "
            "retire-principle so contributors know the over-cap remedy",
        )


class TestWorkSelectionUsesScheduledStatus(unittest.TestCase):
    """xp-work-selection moves stories to `scheduled`, not `in-progress`.

    The four-state lifecycle (ready → scheduled → in-progress → done/deferred)
    means work-selection picks for THIS iteration and parks at `scheduled`.
    xp-assign promotes to in-progress when it creates the branch. Pinning the
    SKILL.md instructions so a regression to `in-progress` (the old shape)
    can't slip in unnoticed.
    """

    @classmethod
    def setUpClass(cls):
        path = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-work-selection"
            / "SKILL.md"
        )
        cls.content = path.read_text()

    def test_update_story_uses_scheduled(self):
        self.assertIn("update-story story-NNN scheduled", self.content)

    def test_no_update_story_in_progress(self):
        # Old shape removed — work-selection no longer transitions to
        # in-progress directly. xp-assign owns that transition.
        self.assertNotIn("update-story story-NNN in-progress", self.content)

    def test_status_event_says_scheduled(self):
        self.assertIn("marked N stories scheduled", self.content)


class TestRetroAnalysisNotesDirectives(unittest.TestCase):
    """M7: retro prompt has analysis_notes read/write directives and Try cap."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent.parent.parent / "agents" / "xp-retrospective.md"
        cls.content = path.read_text()

    def test_analysis_notes_write_directive(self):
        self.assertIn("analysis_notes", self.content)
        self.assertIn("600", self.content)

    def test_analysis_notes_read_directive(self):
        self.assertIn("previous_retros[0].analysis_notes", self.content)

    def test_try_cap_guidance(self):
        self.assertIn("max 4", self.content.lower())


class TestQualityReviewFramings(unittest.TestCase):
    """/xp-quality-review SKILL.md exposes two framings for plan-review
    concerns: RESOLVE (verify staged changes address it + Resolves-Event
    trailer) and COURAGE-FIX (this concern's files overlap the open
    diff — fix it now while the file is open). Pinned to anchor-bounded
    sections so prose churn outside these regions doesn't false-green
    the assertions.
    """

    @classmethod
    def setUpClass(cls):
        path = (
            Path(__file__).parent.parent.parent
            / "skills"
            / "xp-quality-review"
            / "SKILL.md"
        )
        cls.content = path.read_text()

    def _section(self, header: str, end_header: str) -> str:
        start = self.content.index(header)
        end = self.content.index(end_header, start + 1)
        return self.content[start:end]

    def test_resolve_framing_present(self):
        # Step 3 frames the resolve path; the trailer/resolves wiring
        # is the load-bearing detail. (Renumbered in sprint-113 story-002
        # when the classifier step was removed and the reviewer spawn
        # collapsed to Step 2.)
        section = self._section("## Step 3:", "## Step 4:")
        self.assertIn("Resolved:", section)
        self.assertIn('"resolves":', section)

    def test_courage_fix_framing_present(self):
        # Step 4 carries the COURAGE-FIX framing alongside the existing
        # "Fix directly" guidance: fix concerns whose files overlap the
        # open diff while the file is already open.
        section = self._section("## Step 4:", "## Step 5:")
        self.assertIn("COURAGE-FIX", section)
        self.assertIn("fix it now while the file is open", section)
        self.assertIn("file overlap is in scope", section)


class TestRetroAgingReferences(unittest.TestCase):
    """M5: retro prompt no longer references Risks pillar for aging."""

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent.parent.parent / "agents" / "xp-retrospective.md"
        cls.content = path.read_text()

    def test_no_risks_pillar_aging_markers(self):
        self.assertNotIn("⚠️", self.content)
        self.assertNotIn("🔴", self.content)

    def test_no_smm_risks_pillar_reference_for_aging(self):
        self.assertNotIn("SMM's Risks pillar", self.content)


if __name__ == "__main__":
    unittest.main()
