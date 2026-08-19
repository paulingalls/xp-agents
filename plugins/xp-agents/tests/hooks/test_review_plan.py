#!/usr/bin/env python3
"""Tests for xp-review-plan preload: path-based output.

Preload should output file paths (SMM_FILE, PLAN_FILE, SPRINT_FILE)
instead of dumping full file contents to stdout.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _system_context_fixtures import write_doc as write_system_context_doc
from conftest import (
    _IntegrationTestCase,
    write_smm_fixture,
)

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-review-plan"
    / "scripts"
    / "preload.sh"
)

_SAMPLE_PLAN = """\
# Implementation Plan

## Step 1: Add user model
- File: src/models/user.py
"""


def _write_sample_smm(smm_dir):
    write_smm_fixture(
        smm_dir,
        intent=[("Ship v1", "goal")],
        constraints=[("TDD always", "convention")],
        risks=[("Auth fragile", "concern", "problem")],
        wisdom=["Commit after green"],
    )


class TestReviewPlanPreload(_IntegrationTestCase):
    """Preload outputs file paths, not content."""

    def setUp(self):
        super().setUp()
        self._plans_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self._plans_dir, ignore_errors=True)
        super().tearDown()

    def _write_plan(self, content: str = _SAMPLE_PLAN) -> Path:
        plan_file = self._plans_dir / "test-plan.md"
        plan_file.write_text(content)
        return plan_file

    def test_preload_outputs_smm_dir(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_smm_file_path(self):
        """SMM_FILE= path output, NOT full SMM content."""
        _write_sample_smm(self.smm_dir)
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_FILE=", result.stdout)
        # Content should NOT be in stdout
        self.assertNotIn("TDD always", result.stdout)
        self.assertNotIn("Auth fragile", result.stdout)

    def test_preload_outputs_plan_file_path(self):
        """PLAN_FILE= path output, NOT full plan content."""
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN_FILE=", result.stdout)
        # Plan content should NOT be in stdout
        self.assertNotIn("Add user model", result.stdout)

    def test_preload_outputs_sprint_file_path(self):
        """SPRINT_FILE= path when sprint.json exists."""
        (self.smm_dir / "sprint.json").write_text("# Sprint\n- story-001")
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)
        # Sprint content should NOT be in stdout
        self.assertNotIn("story-001", result.stdout)

    def test_preload_misfire_skips_smm_and_sprint_renders(self):
        """No plan marker → SMM_FILE/SPRINT_FILE NOT emitted (token-trim YAGNI prune).

        When there's no plan to review, the SMM and sprint renders are wasted
        tokens — short-circuit before doing them.
        """
        _write_sample_smm(self.smm_dir)
        (self.smm_dir / "sprint.json").write_text("# Sprint\n- story-001")
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SMM_FILE=", result.stdout)
        self.assertNotIn("SPRINT_FILE=", result.stdout)
        self.assertIn("PLAN_FILE_ERROR=", result.stdout)

    def test_preload_no_sprint_file_omits_path(self):
        """No SPRINT_FILE= when sprint.json doesn't exist."""
        sprint = self.smm_dir / "sprint.json"
        if sprint.exists():
            sprint.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SPRINT_FILE=", result.stdout)

    def test_preload_leaves_the_plan_marker(self):
        """Marker file survives the preload: it is not this script's to spend.

        It used to be deleted here, which put the discharge at review START — so
        an opened-and-abandoned /xp-review-plan left the lead un-gated, and on the
        harness where a shell read of SKILL.md triggers the preload, reading the
        skill body was enough. story-021 moved it to the reviewer's completion
        (`subagent_stop._handle_plan_review_done`); see
        tests/hooks/test_gate_discharge.py.
        """
        plan_path = self._write_plan()
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text(str(plan_path))
        self._run_preload(_PRELOAD_SCRIPT)
        self.assertTrue(marker.exists())

    def test_preload_no_plan_exits_ok(self):
        """No plan marker → exits 0, PLAN_FILE not in output."""
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preload_clean_home_no_plans_dir(self):
        """Preload exits 0 when ~/.claude/plans/ doesn't exist (CI env)."""
        clean_home = tempfile.mkdtemp()
        try:
            result = self._run_preload(_PRELOAD_SCRIPT, extra_env={"HOME": clean_home})
            self.assertEqual(
                result.returncode,
                0,
                f"Should not fail with clean HOME: {result.stderr}",
            )
            self.assertNotIn("PLAN_FILE=", result.stdout)
        finally:
            import shutil

            shutil.rmtree(clean_home, ignore_errors=True)

    def test_preload_persists_plan_path_for_assign(self):
        """Preload writes .last-plan-path for xp-assign to read."""
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        self._run_preload(_PRELOAD_SCRIPT)
        marker = self.smm_dir / ".last-plan-path"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text().strip(), str(plan_path))

    def test_preload_emits_system_context_rendered_when_present(self):
        """SYSTEM_CONTEXT_RENDERED= path emitted when system_context.json exists.

        Plan-reviewer gets the WHERE layer of the layered read path
        (system_context=WHERE / milestone=WHY / story=WHAT) — without it
        the reviewer cites the model conceptually but never sees it.
        """
        write_system_context_doc(self.smm_dir)
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SYSTEM_CONTEXT_RENDERED=", result.stdout)
        # Content should NOT be in stdout — path only.
        self.assertNotIn("A test product.", result.stdout)

    def test_preload_omits_system_context_when_missing(self):
        """No SYSTEM_CONTEXT_RENDERED= when system_context.json doesn't exist."""
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SYSTEM_CONTEXT_RENDERED=", result.stdout)

    def test_preload_rereview_falls_back_to_last_plan_path(self):
        """Second invocation with no marker re-reviews the same plan.

        Reproduces the live bug: a first pass consumes the marker, so an
        explicitly requested re-review must not error with 'No plan marker'
        — it should return the same PLAN_FILE. This is the AC-4 pin: a
        further review stays AVAILABLE even though nothing demands one.
        """
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        first = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn(f"PLAN_FILE={plan_path}", first.stdout)

        second = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotIn("PLAN_FILE_ERROR=", second.stdout)
        self.assertIn(f"PLAN_FILE={plan_path}", second.stdout)

    def test_preload_marker_pass_tags_plan_source_marker(self):
        """First pass (marker present) tags PLAN_SOURCE=marker."""
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN_SOURCE=marker", result.stdout)

    def test_preload_rereview_tags_plan_source_last_reviewed(self):
        """Second pass (no marker, fallback) tags PLAN_SOURCE=last-reviewed.

        The marker is removed between the two runs BY HAND, standing in for the
        act that removes it in production: the plan reviewer completing
        (`subagent_stop._handle_plan_review_done`). It used to disappear because
        the first preload run deleted it, which is exactly what story-021
        stopped — so this fixture now has to say what a re-review is a second
        pass AFTER.
        """
        plan_path = self._write_plan()
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text(str(plan_path))
        self._run_preload(_PRELOAD_SCRIPT)
        marker.unlink()

        second = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("PLAN_SOURCE=last-reviewed", second.stdout)

    def test_preload_leaves_a_gate_only_a_completed_review_can_clear(self):
        """Gate pin, inverted by story-021 and still about the same risk.

        lead_gates registers PLAN_AWAITING_REVIEW with no active_when, so it
        stays armed until the marker file disappears — which is why "who removes
        it" matters at all. That is now the reviewer's completion, not this
        script, so the pin here is that a successful first pass leaves it. The
        old worry (do not trade a broken re-review for a permanently blocked
        lead) is answered by re-running /xp-review-plan to completion: the gate
        is never consulted on a Skill call, only on Write/Edit/MultiEdit.
        """
        plan_path = self._write_plan()
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.exists())

    def test_preload_dead_marker_then_rereview_does_not_resurrect_stale_plan(self):
        """Two-invocation sequence: dead marker error must NOT poison the fallback.

        approve plan A -> succeeds, .last-plan-path=A
        approve plan B -> B's file dies -> invalid-marker error
        re-run          -> must NOT silently emit plan A via last-reviewed fallback
        """
        plan_a = self._write_plan(content=_SAMPLE_PLAN)
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text(str(plan_a))
        first = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn(f"PLAN_FILE={plan_a}", first.stdout)

        dead_plan_b = self._plans_dir / "plan-b-dead.md"
        marker.write_text(str(dead_plan_b))
        second = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("PLAN_FILE_ERROR=", second.stdout)

        third = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertNotIn(f"PLAN_FILE={plan_a}", third.stdout)
        self.assertIn("PLAN_FILE_ERROR=No plan marker", third.stdout)

    def test_preload_dead_marker_error_unchanged(self):
        """Marker naming a dead file still reports the existing invalid-marker error."""
        marker = self.smm_dir / ".plan-awaiting-review"
        marker.write_text(str(self._plans_dir / "does-not-exist.md"))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN_FILE_ERROR=Marker", result.stdout)
        self.assertIn("invalid", result.stdout)

    def test_preload_no_marker_no_last_plan_path_reports_no_plan_marker(self):
        """Neither marker nor .last-plan-path -> existing 'No plan marker' error."""
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        last_plan = self.smm_dir / ".last-plan-path"
        if last_plan.exists():
            last_plan.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN_FILE_ERROR=No plan marker", result.stdout)

    def test_preload_last_plan_path_names_dead_file_falls_through(self):
        """.last-plan-path names a dead file -> no dead path emitted."""
        dead_plan = self._plans_dir / "since-deleted.md"
        (self.smm_dir / ".last-plan-path").write_text(str(dead_plan))
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(f"PLAN_FILE={dead_plan}", result.stdout)
        self.assertIn("PLAN_FILE_ERROR=No plan marker", result.stdout)

    def test_preload_system_context_tempfile_carries_plan_reviewer_subset(self):
        """Rendered tempfile contains the plan-reviewer subset.

        Plan-reviewer needs product+architecture+modules+stack+conventions
        full, plus principles topics-only. No project_specific bodies.
        """
        write_system_context_doc(self.smm_dir)
        plan_path = self._write_plan()
        (self.smm_dir / ".plan-awaiting-review").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Extract the path
        line = next(
            line
            for line in result.stdout.splitlines()
            if line.startswith("SYSTEM_CONTEXT_RENDERED=")
        )
        rendered_path = Path(line.split("=", 1)[1])
        self.assertTrue(rendered_path.exists(), f"tempfile {rendered_path} missing")
        rendered = rendered_path.read_text()
        self.assertIn("## Product", rendered)
        self.assertIn("## Architecture Overview", rendered)
        self.assertIn("## Stack", rendered)
        self.assertIn("## Conventions", rendered)
        self.assertIn("## Principles (topics)", rendered)
        # principles content collapsed to topic bullet
        self.assertIn("- language", rendered)
        self.assertNotIn("Use Python", rendered)


if __name__ == "__main__":
    unittest.main()
