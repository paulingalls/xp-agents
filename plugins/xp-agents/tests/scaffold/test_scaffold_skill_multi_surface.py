#!/usr/bin/env python3
"""Tests for /xp-scaffold-acceptance SKILL.md M-1 multi-surface loop.

Markdown-shape assertions only — no script execution. Story-004 rewrites
Steps 3-9 into a single-invocation multi-surface flow: (1) list-uncovered
gathers the surfaces, (2) one confirmation page maps each surface to its
default canonical tool, (3) Steps 2 and 4-9 loop once per confirmed surface,
(4) Step 10 renders a per-surface created/resumed/skipped summary.

The single-surface pin anchors live in test_scaffold_skill.py /
test_scaffold_skill_m3.py and must still pass — this file pins only the
multi-surface additions.
"""

import unittest
from pathlib import Path

from _helpers import frontmatter_body, step_section

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "xp-agents"
_SKILL_PATH = _PLUGIN_ROOT / "skills" / "xp-scaffold-acceptance" / "SKILL.md"


class TestMultiSurfaceConfirm(unittest.TestCase):
    """Step 3 lists uncovered surfaces and presents one confirmation page
    mapping each surface to its default canonical tool (AC #1)."""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = frontmatter_body(text)
        cls.step3 = step_section(cls.body, 3)

    def test_step_3_invokes_list_uncovered(self) -> None:
        self.assertIn("list-uncovered", self.step3)
        self.assertIn("--repo-root", self.step3)

    def test_step_3_has_multi_surface_confirmation_page(self) -> None:
        self.assertRegex(self.step3, r"(?i)multi-surface confirmation")

    def test_step_3_confirmation_uses_askuserquestion(self) -> None:
        self.assertIn("AskUserQuestion", self.step3)

    def test_step_3_maps_surface_to_default_canonical_tool(self) -> None:
        """The confirmation page must map each surface to its DEFAULT
        canonical tool (the first canonical_tools entry), not just mention
        canonical tools abstractly."""
        self.assertIn("canonical_tools", self.step3)
        self.assertRegex(self.step3, r"(?i)default")

    def test_step_3_unselected_surfaces_skipped(self) -> None:
        """Surfaces the customer leaves unselected are recorded as skipped,
        not silently dropped."""
        self.assertRegex(self.step3, r"(?i)skip")


class TestPerSurfaceLoopBoundary(unittest.TestCase):
    """Steps 2 and 4-9 are scoped inside a 'for each confirmed surface'
    loop boundary that opens before Step 4 and closes at the summary
    (AC #2)."""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = frontmatter_body(text)

    def test_loop_boundary_phrase_present(self) -> None:
        self.assertRegex(self.body, r"(?i)for each confirmed surface")

    def test_loop_opens_before_step_4(self) -> None:
        loop_idx = self.body.lower().find("for each confirmed surface")
        step4_idx = self.body.find("## Step 4")
        self.assertGreater(loop_idx, -1, "loop boundary phrase missing")
        self.assertGreater(step4_idx, -1, "Step 4 section missing")
        self.assertLess(
            loop_idx,
            step4_idx,
            "the per-surface loop must open before Step 4 so Steps 4-9 fall "
            "inside the iteration body",
        )

    def test_loop_body_names_steps_4_through_9(self) -> None:
        """The loop-boundary prose must name the steps that form the
        iteration body so a reader knows the loop scope."""
        loop_idx = self.body.lower().find("for each confirmed surface")
        window = self.body[loop_idx : loop_idx + 400]
        self.assertRegex(window, r"4\D{0,4}9", "loop body must name Steps 4-9")

    def test_loop_closes_at_summary_after_step_9(self) -> None:
        step9_idx = self.body.find("## Step 9")
        step10_idx = self.body.find("## Step 10")
        self.assertGreater(step9_idx, -1, "Step 9 section missing")
        self.assertGreater(
            step10_idx,
            step9_idx,
            "Step 10 (summary) must follow the per-surface pipeline steps",
        )

    def test_loop_reinterprets_step_exit_as_end_iteration(self) -> None:
        """Steps 5-9 each say 'then exit'; without a loop-scoping override an
        LLM would abort the whole run on the first surface failure, defeating
        the independent-iterations contract. The loop must explicitly reinterpret
        those exits as 'end this iteration, continue to the next surface'."""
        loop_idx = self.body.lower().find("for each confirmed surface")
        window = self.body[loop_idx : loop_idx + 700].lower()
        self.assertIn("exit", window)
        self.assertRegex(
            window,
            r"end this iteration|next (confirmed )?surface|not exit the skill",
            "loop must scope step-level 'exit' to the current iteration",
        )


class TestPerSurfaceSummary(unittest.TestCase):
    """Step 10 renders a per-surface created/resumed/skipped summary, with
    'resumed' sourced from ApplyResult.resumed (story-003 consumer)."""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = frontmatter_body(text)
        cls.step10 = step_section(cls.body, 10)

    def test_step_10_section_present(self) -> None:
        self.assertNotEqual(self.step10.strip(), "", "Step 10 summary section missing")

    def test_step_10_names_three_outcomes(self) -> None:
        lowered = self.step10.lower()
        for outcome in ("created", "resumed", "skipped"):
            self.assertIn(
                outcome,
                lowered,
                f"Step 10 summary must name the {outcome!r} outcome",
            )

    def test_step_10_resumed_from_apply_result(self) -> None:
        """'resumed' must be tied to ApplyResult.resumed so the summary
        reflects the idempotent re-apply path, not a guess."""
        self.assertRegex(self.step10, r"(?i)ApplyResult\.resumed|\.resumed")


class TestRuntimeOrderReflectsLoop(unittest.TestCase):
    """The runtime-order header must communicate that Steps 2 and 4-9 loop
    per surface and Step 10 renders the summary."""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = frontmatter_body(text)

    def test_runtime_order_mentions_per_surface_loop(self) -> None:
        first_step_idx = self.body.find("## Step 1")
        prologue = self.body[:first_step_idx]
        self.assertRegex(
            prologue,
            r"(?i)per[- ]surface|once per|loop",
            "runtime-order prologue must signal the per-surface loop",
        )

    def test_runtime_order_includes_step_10(self) -> None:
        first_step_idx = self.body.find("## Step 1")
        prologue = self.body[:first_step_idx]
        self.assertIn("10", prologue)


if __name__ == "__main__":
    unittest.main()
