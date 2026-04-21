#!/usr/bin/env python3
"""Tests for agent prompt content: purpose filters, aging references, directives.

Split from test_plugin_integrity.py for file size management.
"""

import unittest
from pathlib import Path


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
