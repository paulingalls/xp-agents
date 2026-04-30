#!/usr/bin/env python3
"""Tests for /xp-scaffold-acceptance SKILL.md M-3 wiring.

Covers Step 6 apply-write, Step 7 apply-install + apply-verify, the
runtime-order header, the show-files-uses-plan-bodies contract, and the
manifest full-body responsibility documentation. Helpers and other
milestones live in test_scaffold_skill.py.
"""

import unittest
from pathlib import Path

from _helpers import frontmatter_body, step_section

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "xp-agents"
_SKILL_PATH = _PLUGIN_ROOT / "skills" / "xp-scaffold-acceptance" / "SKILL.md"


class TestSkillM3Wiring(unittest.TestCase):
    """M-3 wiring: Step 6 apply-write, Step 7 apply-install + apply-verify;
    runtime-order header; show-files uses plan bodies; manifest full-body
    responsibility documented."""

    @classmethod
    def setUpClass(cls) -> None:
        text = _SKILL_PATH.read_text(encoding="utf-8")
        _, cls.body = frontmatter_body(text)

    def test_runtime_order_line_present_near_top(self) -> None:
        first_step_idx = self.body.find("## Step 1")
        self.assertGreater(first_step_idx, 0, "Step 1 section missing")
        prologue = self.body[:first_step_idx]
        self.assertRegex(
            prologue,
            r"1\s*[→-]>?\s*3\s*[→-]>?\s*2",
            "Prologue must name actual runtime order 1→3→2→4→5",
        )

    def test_step_5_show_files_uses_plan_bodies(self) -> None:
        step5 = step_section(self.body, 5)
        self.assertRegex(
            step5,
            r"(?i)\$?PLAN_JSON|render-preview\s+--show-files|files_to_create\[\]\.body",
            "Step 5 show-files branch must read bodies from the plan, not "
            "from working memory",
        )

    def test_step_6_invokes_apply_write_subcommand(self) -> None:
        step6 = step_section(self.body, 6)
        self.assertIn("scaffold_cli.py", step6)
        self.assertIn("apply-write", step6)

    def test_step_6_documents_full_body_manifest_responsibility(self) -> None:
        step6 = step_section(self.body, 6)
        self.assertRegex(
            step6,
            r"(?i)full[- ]body|complete\s+(?:manifest\s+)?body|deep[- ]merge",
            "Step 6 must document that files_to_modify entries carry the full "
            "merged manifest body — apply.py is format-agnostic",
        )

    def test_step_7_invokes_apply_install_and_apply_verify(self) -> None:
        step7 = step_section(self.body, 7)
        self.assertIn("apply-install", step7)
        self.assertIn("apply-verify", step7)

    def test_step_7_references_apply_revert_for_cancel_path(self) -> None:
        step7 = step_section(self.body, 7)
        self.assertIn("apply-revert", step7)

    def test_step_7_surfaces_failure_reason_verbatim(self) -> None:
        step7 = step_section(self.body, 7)
        self.assertRegex(
            step7,
            r"(?i)reason|stderr|verbatim",
            "Step 7 must surface phase failure reason to the customer",
        )

    def test_step_6_uses_repo_root_flag(self) -> None:
        step6 = step_section(self.body, 6)
        self.assertIn("--repo-root", step6)

    def test_step_7_uses_snapshot_id_flag(self) -> None:
        step7 = step_section(self.body, 7)
        self.assertIn("--snapshot-id", step7)

    def test_runtime_order_section_shows_repo_root_assignment(self) -> None:
        """$REPO_ROOT is referenced in Steps 6-7 examples; the prologue
        must show a concrete assignment so the LLM doesn't have to invent
        one. Use the canonical `${REPO_ROOT:-$(pwd)}` form so an
        out-of-band override survives."""
        first_step_idx = self.body.find("## Step 1")
        prologue = self.body[:first_step_idx]
        self.assertRegex(
            prologue,
            r"REPO_ROOT=.*\$\{REPO_ROOT:-\$\(pwd\)\}",
            "Prologue must show the canonical "
            "REPO_ROOT=${REPO_ROOT:-$(pwd)} assignment so an out-of-band "
            "override survives the fallback",
        )

    def test_step_7_warns_against_orphan_install_state(self) -> None:
        """Customer must run apply-install → apply-verify-or-apply-revert as a
        contiguous pair. Leaving install state without verify or revert
        leaks the snapshot dir under TMPDIR (since apply-install does not
        cleanup; cleanup only happens at apply-verify ok or apply-revert)."""
        step7 = step_section(self.body, 7)
        self.assertRegex(
            step7,
            r"(?i)must|never abandon|always (?:run|follow)",
            "Step 7 must instruct the customer that apply-install requires "
            "a follow-up apply-verify or apply-revert",
        )
        self.assertIn("apply-install", step7)
        self.assertIn("apply-verify", step7)
        self.assertIn("apply-revert", step7)


if __name__ == "__main__":
    unittest.main()
