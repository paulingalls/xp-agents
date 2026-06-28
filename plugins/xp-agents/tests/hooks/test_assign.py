#!/usr/bin/env python3
"""Tests for xp-assign preload integration.

Covers: preload.sh output (SMM, sprint, plan, guide), graceful degradation,
and the SKILL.md prose pins for the narrowed (teammate-only) xp-assign.
"""

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

    def test_sprint_is_optional_context(self):
        """Sprint data is described as optional, not required."""
        self.assertIn("optional", self.content.lower())


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

    def test_spawn_passes_plugin_dir(self):
        """Spawn command passes --plugin-dir ${CLAUDE_PLUGIN_ROOT}. Without it
        the headless worktree teammate loads none of the xp-agents skills,
        agents, or hooks (project-scoped marketplace enablement is not applied
        in that session), silently dropping the entire review/commit gate
        lifecycle the CLI-teammate design depends on."""
        self.assertIn("--plugin-dir ${CLAUDE_PLUGIN_ROOT}", self.content)


class TestSkillMdNarrowedToTeammate(unittest.TestCase):
    """story-003: xp-assign narrowed to parallel-only. The decide-half (mode
    question, promotion, solo-branch) moved to /xp-schedule; xp-assign keeps
    only the post-review teammate split + branch + spawn, and consumes the
    preload-computed TEAMMATE_STORY_IDS instead of inline scheduled-selection.
    """

    def setUp(self):
        self.content = _SKILL_MD.read_text()

    def test_no_mode_selection_section(self):
        self.assertNotIn("## Mode Selection", self.content)

    def test_no_solo_mode_section(self):
        self.assertNotIn("## Solo Mode", self.content)

    def test_no_mode_question(self):
        # The solo/parallel decision (AskUserQuestion) is /xp-schedule's now.
        self.assertNotIn("AskUserQuestion", self.content)

    def test_no_overlap_or_count_predicate(self):
        # The decide-half predicate (count-status / scheduled-overlap) is gone.
        self.assertNotIn("scheduled-overlap", self.content)
        self.assertNotIn("count-status scheduled", self.content)

    def test_no_promotion(self):
        # /xp-schedule promotes scheduled->in-progress; xp-assign no longer does.
        self.assertNotIn("update-story", self.content)

    def test_consumes_teammate_story_ids(self):
        # The teammate batch comes from the preload, not inline selection.
        self.assertIn("TEAMMATE_STORY_IDS", self.content)

    def test_keeps_teammate_branch_creation(self):
        # xp-assign still creates the teammate branches at spawn.
        self.assertIn("branching.py", self.content)

    def test_description_is_parallel_only(self):
        # Frontmatter no longer claims the decide-half (solo vs CLI).
        self.assertNotIn("solo vs CLI teammates", self.content)


class TestSkillMdPerStoryShape(unittest.TestCase):
    """story-003: xp-assign reshaped from "split one batch plan + parallel-spawn
    all teammates" to "spawn ONE teammate per invocation — the next un-spawned
    story in TEAMMATE_STORY_IDS, with executor_model forwarded to --model".
    """

    def setUp(self):
        self.content = _SKILL_MD.read_text()

    def test_documents_per_story_single_spawn(self):
        # The prose names the new shape: exactly one spawn per invocation, not
        # a parallel fan-out. "per-story" is the canonical vocabulary in the
        # M2 design + the upstream /xp-schedule tail (shipped in story-001).
        self.assertIn("per-story", self.content)

    def test_documents_lowest_id_un_spawned_target(self):
        # The auto-detect rule the prose codifies, distinctive enough to
        # detect drift toward an alternative target-selection strategy.
        self.assertIn("lowest-id un-spawned", self.content)

    def test_uses_find_teammate_worktree_for_target_detection(self):
        # The shipped detection helper the prose names for spawn idempotency.
        # CLI form ("find-teammate-worktree") is what the skill invokes.
        self.assertIn("find-teammate-worktree", self.content)

    def test_pairs_executor_model_with_model_flag(self):
        # Story-002 schema → story-003 forward. Prose must name both the
        # source field and the destination flag in the same body so the
        # contract is auditable.
        self.assertIn("executor_model", self.content)
        self.assertIn("--model", self.content)

    def test_no_legacy_split_phrase(self):
        # Current frontmatter description says "Split a reviewed teammate-mode
        # plan per teammate" — the canonical legacy phrasing. The reshape
        # removes both the action and the wording.
        self.assertNotIn("Split a reviewed", self.content)

    def test_no_parallel_spawn_fanout(self):
        # The legacy CLI Teammate Mode ended with the instruction
        # "Spawn all teammates in parallel (multiple Bash calls in one message)" —
        # the parallel fan-out signature. The reshape spawns one per invocation;
        # this directive must be gone. (Note: the new target-lookup legitimately
        # uses its own `for sid in` loop to find the lowest un-spawned story,
        # so pinning on the bare loop signature would over-trigger.)
        self.assertNotIn("Spawn all teammates in parallel", self.content)


if __name__ == "__main__":
    unittest.main()
