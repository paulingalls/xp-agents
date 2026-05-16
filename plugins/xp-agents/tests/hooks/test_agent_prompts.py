#!/usr/bin/env python3
"""Tests for agent prompt content: purpose filters, aging references, directives.

Split from test_plugin_integrity.py for file size management.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import system_context_schema

# Window large enough to cover the entire 'Update-mode cap awareness'
# paragraph (~480 chars today). If the paragraph grows past this, the
# pin will report 'soft cap' or 'retire-' missing even when present
# below — bump the window rather than weakening the scoped check.
_UPDATE_MODE_WINDOW_CHARS = 500


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


class TestSystemAnalyzerPromptMaxlengthSync(unittest.TestCase):
    """Sync check: xp-system-analyzer.md's Step 4 JSON template budgets
    must match system_context_schema.FIELD_MAXLENGTH. Without this pin,
    a future schema bump that forgets to update the markdown (or vice
    versa) would silently feed the analyzer stale guidance — its output
    would then fail validation downstream with no obvious cause.
    """

    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent.parent.parent / "agents" / "xp-system-analyzer.md"
        cls.content = path.read_text()

    def test_architecture_overview_budget_matches_schema(self):
        expected = system_context_schema.FIELD_MAXLENGTH["architecture_overview"]
        self.assertIn(
            f"max {expected} chars",
            self.content,
            f"Step 4 template must say 'max {expected} chars' for "
            "architecture_overview — schema/markdown drift detected",
        )

    def test_product_budget_matches_schema(self):
        expected = system_context_schema.FIELD_MAXLENGTH["product"]
        self.assertIn(
            f"max {expected} chars",
            self.content,
            f"Step 4 template must say 'max {expected} chars' for "
            "product — schema/markdown drift detected",
        )

    def test_field_string_caps_pinned_in_template(self):
        """Every leaf string cap from system_context_schema must appear
        in the analyzer template as 'max N chars'."""
        cases = (
            (
                "stack.languages item",
                system_context_schema.STACK_LANGUAGE_ITEM_MAXLENGTH,
            ),
            ("stack field", system_context_schema.STACK_FIELD_MAXLENGTH),
            ("modules.name", system_context_schema.MODULE_NAME_MAXLENGTH),
            ("modules.path", system_context_schema.MODULE_PATH_MAXLENGTH),
            (
                "modules.purpose",
                system_context_schema.MODULE_FIELD_MAXLENGTH["purpose"],
            ),
            ("conventions item", system_context_schema.CONVENTION_MAXLENGTH),
            ("principles.topic", system_context_schema.PRINCIPLE_TOPIC_MAXLENGTH),
            (
                "principles.decision",
                system_context_schema.PRINCIPLE_FIELD_MAXLENGTH["decision"],
            ),
            (
                "principles.rationale",
                system_context_schema.PRINCIPLE_FIELD_MAXLENGTH["rationale"],
            ),
            (
                "project_specific.name",
                system_context_schema.PROJECT_SPECIFIC_NAME_MAXLENGTH,
            ),
            (
                "project_specific.content",
                system_context_schema.PROJECT_SPECIFIC_CONTENT_MAXLENGTH,
            ),
            (
                "acceptance_surfaces.name",
                system_context_schema.ACCEPTANCE_SURFACE_NAME_MAXLENGTH,
            ),
            (
                "acceptance_surfaces.harness",
                system_context_schema.ACCEPTANCE_SURFACE_HARNESS_MAXLENGTH,
            ),
            (
                "acceptance_surfaces.signal",
                system_context_schema.ACCEPTANCE_SURFACE_SIGNAL_MAXLENGTH,
            ),
        )
        for field, expected in cases:
            with self.subTest(field=field):
                self.assertIn(
                    f"max {expected} chars",
                    self.content,
                    f"Step 4 template missing 'max {expected} chars' for "
                    f"{field} — schema/markdown drift detected",
                )

    def test_count_caps_pinned_in_template(self):
        """Soft/hard count caps for capped lists must appear in the
        template as 'N soft / M hard'. Bullet-formatted for scanability.
        """
        cases = (
            (
                "modules",
                system_context_schema.MODULES_SOFT_CAP,
                system_context_schema.MODULES_HARD_CAP,
            ),
            (
                "conventions",
                system_context_schema.CONVENTIONS_SOFT_CAP,
                system_context_schema.CONVENTIONS_HARD_CAP,
            ),
            (
                "principles",
                system_context_schema.PRINCIPLES_SOFT_CAP,
                system_context_schema.PRINCIPLES_HARD_CAP,
            ),
            (
                "project_specific",
                system_context_schema.PROJECT_SPECIFIC_SOFT_CAP,
                system_context_schema.PROJECT_SPECIFIC_HARD_CAP,
            ),
            (
                "acceptance_surfaces",
                system_context_schema.ACCEPTANCE_SURFACES_SOFT_CAP,
                system_context_schema.ACCEPTANCE_SURFACES_HARD_CAP,
            ),
        )
        for field, soft, hard in cases:
            with self.subTest(field=field):
                self.assertIn(
                    f"{soft} soft / {hard} hard",
                    self.content,
                    f"Step 4 template missing '{soft} soft / {hard} hard' "
                    f"for {field} — schema/markdown drift detected",
                )

    def test_discriminator_phrases_pinned(self):
        """Verbatim discriminator-test phrases from SYSTEM_CONTEXT_REDESIGN
        §2/§3 must appear in Step 4. Without these the rename to
        `principles` and the tightened field definitions lose the
        analytical lens that resists diary-shaped accumulation.
        """
        cases = (
            (
                "negation framing",
                "Record what defines this project, not what was decided along the way",
            ),
            ("reversal test", "reversed, makes this a different project"),
            ("navigation-index test", "where do I put new code"),
            ("session-relevance test", "within the session"),
        )
        for label, phrase in cases:
            with self.subTest(phrase=label):
                self.assertIn(
                    phrase,
                    self.content,
                    f"Step 4 missing verbatim {label} phrase — analyzer "
                    "loses its discriminator lens",
                )

    def test_update_mode_retire_first_pinned(self):
        # Scope substring check to the "Update-mode cap awareness" anchor
        # so an unrelated `retire-module` mention elsewhere can't satisfy
        # the pin — without the window, the assertion is decorative.
        anchor = "Update-mode cap awareness"
        self.assertIn(
            anchor,
            self.content,
            "Step 4 must contain the 'Update-mode cap awareness' "
            "anchor so cap-aware retire-first guidance is locatable",
        )
        start = self.content.index(anchor)
        window = self.content[start : start + _UPDATE_MODE_WINDOW_CHARS]
        for needle, why in (
            ("retire-", "cite a retire-* subcommand"),
            ("soft cap", "reference 'soft cap' for the trigger"),
        ):
            with self.subTest(needle=needle):
                self.assertIn(
                    needle,
                    window,
                    f"Update-mode cap awareness paragraph must {why}",
                )

    def test_update_mode_refinement_pinned(self):
        # Window-scoped to the "Update-mode refinement" anchor so a
        # stray `edit-module` mention elsewhere can't false-green the
        # pin — analyzer must surface ALL 5 edit-* commands together
        # at the refinement guidance, not scattered across the doc.
        anchor = "Update-mode refinement"
        self.assertIn(
            anchor,
            self.content,
            "Step 4 must contain the 'Update-mode refinement' anchor "
            "so per-entry edit-* guidance is locatable",
        )
        start = self.content.index(anchor)
        window = self.content[start : start + _UPDATE_MODE_WINDOW_CHARS]
        for cmd in (
            "edit-module",
            "edit-principle",
            "edit-convention",
            "edit-project-specific",
            "edit-acceptance-surface",
        ):
            with self.subTest(cmd=cmd):
                self.assertIn(
                    cmd,
                    window,
                    f"Update-mode refinement paragraph must cite {cmd!r}",
                )


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
