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


class TestSystemAnalyzerDetectsTestCommand(unittest.TestCase):
    """xp-system-analyzer auto-detects stack.test_command on new
    projects via a per-language signal table (Step 3.7). Without
    this detection, every fresh `/xp-system-context` run would leave
    test_command unset and the close-skill auto-merge gate would
    silently never fire — defeating the point of the field.

    Pin (a) the Step 3.7 section heading exists, (b) it lists
    detection signals for the major language ecosystems, (c) the
    Step 4 JSON template includes the test_command field so the
    detected value actually flows into system_context.
    """

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent.parent.parent / "agents" / "xp-system-analyzer.md"
        cls.content = path.read_text()

    def test_step_3_7_section_present(self):
        # Heading shape pinned so a future edit can't silently rename
        # or drop the section.
        self.assertIn(
            "### Step 3.7: Test Command Detection",
            self.content,
            "xp-system-analyzer.md must include a 'Step 3.7: Test "
            "Command Detection' section so /xp-system-context auto-"
            "populates stack.test_command on new projects",
        )

    def test_step_3_7_lists_per_language_signals(self):
        # The detection table must cover the major ecosystems the
        # plugin's likely users build in. Pin one signal phrase per
        # ecosystem so dropping a row fails loudly. subTest reports
        # each missing signal individually rather than masking after
        # the first.
        for signal in (
            "package.json",  # npm/yarn/pnpm test
            "pyproject.toml",  # pytest
            "Cargo.toml",  # cargo test
            "go.mod",  # go test
            "mix.exs",  # mix test
            "Makefile",  # make test
        ):
            with self.subTest(signal=signal):
                self.assertIn(
                    signal,
                    self.content,
                    f"Step 3.7 detection table must list `{signal}` "
                    f"as a test-command signal so the analyzer "
                    f"recognizes that ecosystem",
                )

    def test_step_3_7_when_uncertain_leave_unset_rule(self):
        # Critical safety rule: a wrong test command is worse than
        # none (it would fail spuriously and block the gate, or skip
        # real tests and let bad merges through). Pin the rule so a
        # future edit can't silently relax it to "guess your best".
        self.assertIn(
            "leave `test_command` unset",
            self.content,
            "Step 3.7 must instruct the analyzer to leave test_command "
            "unset when detection signals are ambiguous",
        )

    def test_step_4_template_includes_test_command(self):
        # Detection only matters if the value reaches the create-mode
        # JSON. Pin that the Step 4 template lists test_command in
        # the stack object so the analyzer's output flows through.
        self.assertIn(
            '"test_command":',
            self.content,
            "Step 4 JSON template must include `test_command` in the "
            "stack object so detected values propagate to "
            "system_context.json on create",
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
