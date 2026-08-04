#!/usr/bin/env python3
"""Tests for xp-system-analyzer agent prompt: test command detection, maxlength sync."""

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

# Window large enough to cover the principles bullet + its 6-row routing
# table + the "Not in system_context at all" trailing line (~1400 chars
# today). Bump rather than weaken if the table grows.
_ROUTING_TABLE_WINDOW_CHARS = 1500


def _read_system_analyzer_agent() -> str:
    """Return the xp-system-analyzer agent markdown. Single source of the
    analyzer path resolution shared by the analyzer test classes."""
    path = Path(__file__).parent.parent.parent / "agents" / "xp-system-analyzer.md"
    return path.read_text()


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
        cls.content = _read_system_analyzer_agent()

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


class TestSystemAnalyzerDetectsWorktreeTeardown(unittest.TestCase):
    """`stack.worktree_teardown` mirrors `worktree_bootstrap`: only record a
    command when the project already documents one, never invent or compose
    it, and leave an existing value alone on update — Step 3.75 states this
    by reference rather than restating the whole discipline.
    """

    @classmethod
    def setUpClass(cls):
        cls.content = _read_system_analyzer_agent()

    def test_worktree_teardown_sentence_present(self):
        self.assertIn(
            "worktree_teardown",
            self.content,
            "Step 3.75 must mention stack.worktree_teardown so the analyzer "
            "records a project-declared teardown command",
        )

    def test_step_4_template_includes_worktree_teardown(self):
        self.assertIn(
            '"worktree_teardown":',
            self.content,
            "Step 4 JSON template must include worktree_teardown in the "
            "stack object so a detected value propagates to system_context.json",
        )


class TestSystemAnalyzerNamespaceInstruction(unittest.TestCase):
    """`user_namespace` is now READ when naming branches, so the analyzer's
    instruction for it must not clobber a prefix already in use.

    While the field was inert, "derive it from the git email local-part" was
    harmless. Now branch creation reads it: an update-mode run that overwrites
    an in-use `<prefix>/...` with the email local-part renames every FUTURE
    branch and orphans the existing ones — the same disagreement between the
    recorded namespace and the real branches that reading the field was meant
    to end, arriving from the writer's side.
    """

    @classmethod
    def setUpClass(cls):
        cls.content = _read_system_analyzer_agent()

    def test_template_prefers_the_prefix_already_in_use(self):
        self.assertIn(
            "prefix already in use",
            self.content,
            "Step 4's user_namespace instruction must tell the analyzer to "
            "record the namespace already in use on existing branches (Step 3 "
            "already runs `git branch -a`) before falling back to the git "
            "email local-part — the field now drives branch creation",
        )

    def test_namespace_is_a_single_segment(self):
        self.assertIn(
            "no `/`",
            self.content,
            "Step 4's user_namespace instruction must state the value is a "
            "single path segment; a slash-bearing namespace creates branches "
            "the branch-name parsers cannot recognize",
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
        cls.content = _read_system_analyzer_agent()

    def test_architecture_overview_budget_matches_schema(self):
        expected = system_context_schema.FIELD_MAXLENGTH["architecture_overview"]
        self.assertIn(
            f"max {expected} chars",
            self.content,
            f"Step 4 template must say 'max {expected} chars' for "
            "architecture_overview — schema/markdown drift detected",
        )

    def test_surface_command_and_paths_are_in_the_template(self):
        """Update mode replaces the WHOLE surfaces array, so the template must
        name the two new fields — otherwise an analyzer run between now and the
        authoring skill silently DROPS values a project declared, and unlike a
        misspelt key nothing reports the loss."""
        for field in ("paths", "command"):
            self.assertIn(
                f'"{field}"',
                self.content,
                f"analyzer surface template must carry {field!r} or update mode "
                "drops it",
            )
        self.assertIn(
            "re-emit any `paths`/`command`",
            self.content,
            "template must tell update mode to re-emit declared values or the "
            "replace-the-whole-array patch deletes them silently",
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
            (
                "acceptance_surfaces.paths item",
                system_context_schema.ACCEPTANCE_SURFACE_PATH_MAXLENGTH,
            ),
            (
                "acceptance_surfaces.command",
                system_context_schema.ACCEPTANCE_SURFACE_COMMAND_MAXLENGTH,
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

    def test_durability_lens_pinned(self):
        """Opening sentence must set the durability bar — every entry
        true a year from now without curation — so the LLM filters
        ANY field, not just principles."""
        self.assertIn(
            "still be true a year from now without curation",
            self.content,
            "Top-of-prompt missing durability lens — analyzer loses "
            "its global filter for transient content",
        )

    def test_principles_routing_table_pinned(self):
        """The principles bullet routes misshapen entries to their
        real destinations via a positive table + a 'nowhere' trailing
        line. Window-scoped to the reversal-test anchor so unrelated
        mentions elsewhere can't false-green the pin.
        """
        anchor = "reversed, makes this a different project"
        self.assertIn(anchor, self.content)
        start = self.content.index(anchor)
        window = self.content[start : start + _ROUTING_TABLE_WINDOW_CHARS]
        for needle, why in (
            ("| Put it in |", "table header marker"),
            ("`stack` field", "stack route"),
            ("`architecture_overview`", "architecture_overview route"),
            ("`modules`", "modules route"),
            ("`conventions`", "conventions route"),
            ("`project_specific`", "project_specific route"),
            ("consolidate", "near-duplicate consolidation"),
            ("Not in system_context at all", "nowhere trailing line"),
        ):
            with self.subTest(needle=why):
                self.assertIn(
                    needle,
                    window,
                    f"principles bullet missing {why} — routing table "
                    "drifted or got dropped",
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


class TestSurfaceAuthoringPrompt(unittest.TestCase):
    """story-017 AC4/AC5. Nothing populates surface `paths`/`command` unless
    the analyzer proposes them, so this prose is the only thing standing
    between the whole 014-017 chain and permanent dormancy.
    """

    def setUp(self) -> None:
        self.md = (
            Path(__file__).parent.parent.parent / "agents" / "xp-system-analyzer.md"
        ).read_text()

    def test_it_proposes_and_confirms_rather_than_inferring(self) -> None:
        self.assertIn("only what they confirm", self.md)

    def test_it_says_why_a_guessed_command_is_dangerous(self) -> None:
        """A rule without its reason gets trimmed by the next editor."""
        self.assertIn("auto-merge", self.md)

    def test_it_proposes_a_residue_surface(self) -> None:
        """Without a command-less surface over the unclaimed paths, the
        all-or-nothing veto means narrowing never fires and every declared
        command is inert."""
        self.assertIn("residue surface", self.md)

    def test_the_residue_surface_carries_no_command(self) -> None:
        self.assertIn("no `command`", self.md)


if __name__ == "__main__":
    unittest.main()
