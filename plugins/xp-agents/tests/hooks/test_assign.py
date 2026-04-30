#!/usr/bin/env python3
"""Tests for xp-assign preload integration.

Covers: preload.sh output (SMM, sprint, plan, guide), graceful degradation.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, write_smm_fixture

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-assign"
    / "scripts"
    / "preload.sh"
)

_SAMPLE_SPRINT = """\
# Sprint: Build user management REST API

- **Sprint ID:** sprint-001
- **Started:** 2026-03-26

## Stories

### story-001: User registration
- **Size:** M
- **Status:** done
- **Dependencies:** none

### story-002: JWT authentication
- **Size:** M
- **Status:** in-progress
- **Dependencies:** story-001
"""

_SAMPLE_PLAN = """\
# Implementation Plan

## Step 1: Add user model
- File: src/models/user.py
- Tests: tests/test_user.py

## Step 2: Add auth endpoints
- File: src/api/auth.py
- Tests: tests/test_auth.py
"""


class TestAssignPreload(_IntegrationTestCase):
    """xp-assign preload: dumps SMM + sprint + plan paths."""

    def _write_plan(self, content: str = _SAMPLE_PLAN) -> Path:
        """Write a plan file and return its path."""
        _, path = tempfile.mkstemp(suffix=".md")
        plan_file = Path(path)
        plan_file.write_text(content)
        return plan_file

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_outputs_plan_file_path(self):
        """PLAN_FILE= path output, NOT full plan content."""
        plan_path = self._write_plan()
        (self.smm_dir / ".last-plan-path").write_text(str(plan_path))
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLAN_FILE=", result.stdout)
        # Plan content should NOT be in stdout
        self.assertNotIn("Add user model", result.stdout)

    def test_preload_outputs_file_paths_not_content(self):
        """SMM_FILE=, SPRINT_FILE= paths, NOT pillar/sprint content."""
        write_smm_fixture(
            self.smm_dir,
            constraints=[("TDD always", "convention")],
            wisdom=["Commit after green"],
        )
        (self.smm_dir / "sprint.json").write_text(_SAMPLE_SPRINT)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_FILE=", result.stdout)
        self.assertIn("SPRINT_FILE=", result.stdout)
        # Content should NOT be in stdout
        self.assertNotIn("TDD always", result.stdout)
        self.assertNotIn("Commit after green", result.stdout)
        self.assertNotIn("sprint-001", result.stdout)

    def test_preload_no_marker_exits_ok(self):
        """No plan marker -> exits 0."""
        marker = self.smm_dir / ".plan-awaiting-review"
        if marker.exists():
            marker.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_preload_clean_home_no_plans_dir(self):
        """Preload exits 0 when ~/.claude/ doesn't exist (CI env)."""
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

    def test_preload_missing_last_plan_path(self):
        """Preload exits 0 when .last-plan-path doesn't exist."""
        marker = self.smm_dir / ".last-plan-path"
        if marker.exists():
            marker.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("PLAN_FILE=", result.stdout)

    def test_preload_stale_last_plan_path(self):
        """Preload exits 0 when .last-plan-path points to deleted file."""
        marker = self.smm_dir / ".last-plan-path"
        marker.write_text("/tmp/nonexistent-plan-abc123.md")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("PLAN_FILE=", result.stdout)

    def test_preload_clears_assign_pending_marker(self):
        """Preload clears .assign-pending marker when it exists."""
        marker = self.smm_dir / ".assign-pending"
        marker.write_text("review-1")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), "assign-pending marker should be cleared")


_SKILL_MD = Path(__file__).parent.parent.parent / "skills" / "xp-assign" / "SKILL.md"


class TestSkillMdPlanPrimary(unittest.TestCase):
    """SKILL.md uses plan file as primary input, sprint as optional context."""

    def setUp(self):
        self.content = _SKILL_MD.read_text()

    def test_preflight_gates_on_plan_file(self):
        """Pre-flight checks gate on PLAN_FILE, not SPRINT_FILE."""
        self.assertIn("PLAN_FILE", self.content)
        self.assertIn("No plan file found", self.content)

    def test_preflight_does_not_gate_on_sprint(self):
        """Pre-flight does NOT stop if sprint is missing."""
        self.assertNotIn("No sprint data", self.content)
        self.assertNotIn("Run `/xp-sprint-start` first", self.content)

    def test_mode_selection_uses_plan_steps(self):
        """Mode selection references plan steps, not sprint stories."""
        self.assertIn("plan", self.content.lower())
        self.assertIn("Mode Selection", self.content)

    def test_sprint_is_optional_context(self):
        """Sprint data is described as optional, not required."""
        self.assertIn("optional", self.content.lower())

    def test_no_session_mode_conditionals(self):
        """No sprint-gated conditionals that would break free session mode."""
        self.assertNotIn("all stories have status", self.content)
        self.assertNotIn("Count stories with status", self.content)


class TestSkillMdCliSpawning(unittest.TestCase):
    """SKILL.md uses CLI teammate spawning via spawn_teammate.py."""

    def setUp(self):
        self.content = _SKILL_MD.read_text()

    def test_references_spawn_teammate_script(self):
        """Spawning uses spawn_teammate.py, not Agent tool."""
        self.assertIn("spawn_teammate.py", self.content)

    def test_references_output_filter(self):
        """Output piped through teammate_output_filter.py."""
        self.assertIn("teammate_output_filter.py", self.content)

    def test_uses_run_in_background(self):
        """Teammates spawned with run_in_background."""
        self.assertIn("run_in_background", self.content)

    def test_no_agent_tool_spawning(self):
        """No Agent tool with xp-teammate subagent_type."""
        self.assertNotIn('subagent_type: "xp-teammate"', self.content)
        self.assertNotIn('subagent_type: "xp-teammate"', self.content)


class TestSkillMdJitBranchCreation(unittest.TestCase):
    """SKILL.md gates branch creation by execution mode (JIT for solo).

    Per the JIT-branch design (decision df47c932fbe6 — JIT story
    branches + close-skill unification): solo mode creates ONLY the
    first in-progress story's branch at /xp-assign time; subsequent
    branches are JIT-created at /xp-story-close after the prior story
    merges. Teammate mode keeps eager creation — all parallel-eligible
    branches at /xp-assign so each teammate has a worktree to spawn into.

    The pre-JIT behavior (eager all-branch creation in solo too) caused
    stale chained branches: story-002 born off the pre-001 sprint tip
    instead of the merged tip. /xp-story-close JIT-creates resolves
    that by creating story-002 off the just-merged code.
    """

    def setUp(self):
        self.content = _SKILL_MD.read_text()

    def test_branch_creation_section_documents_solo_jit_gating(self):
        # Scope to the Branch Creation section so a future revert to
        # eager-all in this section can't false-pass against the
        # unrelated "Solo Mode" section that already says "Checkout
        # the first in-progress story's branch".
        bc_match = re.search(
            r"## Branch Creation.*?\n##\s",
            self.content,
            re.DOTALL,
        )
        assert bc_match is not None, "## Branch Creation section not found"
        branch_creation = bc_match.group(0)
        # Solo's JIT pins on "ONLY the first in-progress" — capitalized
        # to match the SKILL.md's emphasis and to filter out incidental
        # prose elsewhere.
        self.assertIn(
            "ONLY the first in-progress",
            branch_creation,
            "Branch Creation section must describe creating ONLY the "
            "first in-progress story branch in solo mode (JIT — "
            "subsequent branches are created by /xp-story-close after "
            "each prior merge)",
        )

    def test_references_jit_story_close_handoff(self):
        # Solo mode hands off subsequent branch creation to
        # /xp-story-close — the SKILL.md must mention that so a future
        # editor doesn't reintroduce eager creation thinking it was a
        # gap.
        self.assertIn("/xp-story-close", self.content)


if __name__ == "__main__":
    unittest.main()
