#!/usr/bin/env python3
"""Integration tests for xp-assign and teammate workflow.

Covers: preload with multi-story sprints (solo/worktree mode triggers),
WorktreeCreate hook subprocess,
edge cases (missing file domains, all-S stories, dependency chains),
and full E2E pipeline (init SMM, seed sprint, run preload, verify output).
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _IntegrationTestCase,
    _s,
    _sprint_json,
    write_smm_fixture,
)

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD_SCRIPT = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"


class TestWorktreeCreateSubprocess(_IntegrationTestCase):
    """WorktreeCreate hook via subprocess with real git repo."""

    def test_creates_worktree_from_non_default_branch(self):
        """On a non-default branch, worktree is created from that branch."""
        # Create a feature branch
        subprocess.run(
            ["git", "checkout", "-b", "feature/v2"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        # Add a commit on the feature branch so it diverges
        (self.tmpdir / "v2.txt").write_text("v2 content")
        subprocess.run(
            ["git", "add", "v2.txt"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "v2 commit"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # Platform sends name only — hook generates path
        result = self._run_script(
            "worktree_create.py",
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": "test-wt",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        wt_path = result.stdout.strip()
        self.assertTrue(Path(wt_path).is_dir(), "Worktree should exist")

        # v2.txt should be present (branched from feature/v2, not main)
        self.assertTrue(
            (Path(wt_path) / "v2.txt").is_file(),
            "Worktree should contain v2.txt from feature branch",
        )

    def test_creates_worktree_on_default_branch(self):
        """On the default branch, worktree is created normally."""
        result = self._run_script(
            "worktree_create.py",
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": "default-wt",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        wt_path = result.stdout.strip()
        self.assertTrue(Path(wt_path).is_dir())

    def tearDown(self):
        # Clean up worktrees created by tests
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("worktree ") and "worktree-" in line:
                wt = line.split("worktree ", 1)[1]
                subprocess.run(
                    ["git", "worktree", "remove", "--force", wt],
                    cwd=self.tmpdir,
                    capture_output=True,
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_preload_var(stdout: str, name: str) -> str | None:
    """Extract a VAR=value from preload stdout. Returns value or None."""
    prefix = f"{name}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1]
    return None


# ---------------------------------------------------------------------------
# Sprint fixture helpers for mode selection tests
# ---------------------------------------------------------------------------


def _multi_story_sprint_worktree() -> str:
    """Sprint with independent M/L stories and non-overlapping domains."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "User registration",
                "M",
                "ready",
                file_domain=["src/auth/register.py", "tests/test_register.py"],
            ),
            _s(
                "story-002",
                "Admin dashboard",
                "L",
                "ready",
                file_domain=["src/admin/dashboard.py", "tests/test_dashboard.py"],
            ),
        ],
        sprint_id="sprint-001",
        started="2026-04-01",
    )


def _multi_story_sprint_solo_deps() -> str:
    """Sprint with dependency chains (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "User model",
                "M",
                "ready",
                file_domain=["src/models/user.py"],
            ),
            _s(
                "story-002",
                "User API",
                "M",
                "ready",
                file_domain=["src/api/user.py"],
                dependencies=["story-001"],
            ),
        ],
        sprint_id="sprint-002",
        started="2026-04-01",
    )


def _multi_story_sprint_all_small() -> str:
    """Sprint with all S stories (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "Fix typo",
                "S",
                "ready",
                file_domain=["src/ui/header.py"],
            ),
            _s(
                "story-002",
                "Update readme",
                "S",
                "ready",
                file_domain=["docs/README.md"],
            ),
        ],
        sprint_id="sprint-003",
        started="2026-04-01",
    )


def _multi_story_sprint_no_domains() -> str:
    """Sprint with missing file domains (forces solo mode)."""
    return _sprint_json(
        [
            _s("story-001", "Feature A", "M", "ready"),
            _s("story-002", "Feature B", "M", "ready"),
        ],
        sprint_id="sprint-004",
        started="2026-04-01",
    )


def _multi_story_sprint_overlapping_domains() -> str:
    """Sprint with overlapping file domains (forces solo mode)."""
    return _sprint_json(
        [
            _s(
                "story-001",
                "Auth flow",
                "M",
                "ready",
                file_domain=["src/auth/login.py", "src/shared/utils.py"],
            ),
            _s(
                "story-002",
                "Password reset",
                "M",
                "ready",
                file_domain=["src/auth/reset.py", "src/shared/utils.py"],
            ),
        ],
        sprint_id="sprint-005",
        started="2026-04-01",
    )


class TestPreloadMultiStorySprint(_IntegrationTestCase):
    """Preload with various multi-story sprint configurations."""

    def _write_sprint(self, sprint_json: str) -> None:
        """Write sprint data to the SMM directory."""
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def test_preload_with_worktree_eligible_sprint(self):
        """Sprint with independent M/L stories outputs SPRINT_FILE."""
        self._write_sprint(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_with_dependency_chain_sprint(self):
        """Sprint with dependencies still outputs SPRINT_FILE."""
        self._write_sprint(_multi_story_sprint_solo_deps())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_all_small_stories(self):
        """Sprint with all S stories still outputs SPRINT_FILE."""
        self._write_sprint(_multi_story_sprint_all_small())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_no_file_domains(self):
        """Sprint with empty file domains still outputs SPRINT_FILE."""
        self._write_sprint(_multi_story_sprint_no_domains())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_overlapping_domains(self):
        """Sprint with overlapping domains still outputs SPRINT_FILE."""
        self._write_sprint(_multi_story_sprint_overlapping_domains())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_without_sprint_no_sprint_file(self):
        """No sprint.json => no SPRINT_FILE output."""
        sprint_path = self.smm_dir / "sprint.json"
        if sprint_path.exists():
            sprint_path.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SPRINT_FILE=", result.stdout)
        # SMM_DIR should still be present
        self.assertIn("SMM_DIR=", result.stdout)

    def test_sprint_file_path_is_readable(self):
        """SPRINT_FILE path points to a file with rendered sprint content."""
        self._write_sprint(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        sprint_path = _extract_preload_var(result.stdout, "SPRINT_FILE")
        assert sprint_path is not None, "SPRINT_FILE= not found in output"
        sprint_file = Path(sprint_path)
        self.assertTrue(sprint_file.is_file(), f"Sprint file not found: {sprint_file}")

        content = sprint_file.read_text()
        self.assertIn("sprint-001", content)
        self.assertIn("User registration", content)


class TestRenderedSprintForModeSelection(_IntegrationTestCase):
    """Verify rendered sprint content contains data relevant to mode selection.

    Sprint is optional context for story tracking — not the primary input.
    Plan steps drive mode selection. These tests verify that when sprint
    data IS present, it renders correctly for supplementary analysis.
    """

    def _get_rendered_sprint(self, sprint_json: str) -> str:
        """Write sprint, run preload, return rendered sprint content."""
        (self.smm_dir / "sprint.json").write_text(sprint_json)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        sprint_path = _extract_preload_var(result.stdout, "SPRINT_FILE")
        assert sprint_path is not None, "SPRINT_FILE= not found"
        return Path(sprint_path).read_text()

    def test_rendered_sprint_includes_file_domains(self):
        """Rendered sprint shows file domain for mode selection analysis."""
        content = self._get_rendered_sprint(_multi_story_sprint_worktree())
        self.assertIn("src/auth/register.py", content)
        self.assertIn("src/admin/dashboard.py", content)

    def test_rendered_sprint_includes_dependencies(self):
        """Rendered sprint shows dependencies for mode selection analysis."""
        content = self._get_rendered_sprint(_multi_story_sprint_solo_deps())
        self.assertIn("story-001", content)

    def test_rendered_sprint_includes_sizes(self):
        """Rendered sprint shows story sizes for mode selection analysis."""
        content = self._get_rendered_sprint(_multi_story_sprint_all_small())
        # Size S should appear for both stories
        self.assertIn("S", content)

    def test_rendered_sprint_shows_overlapping_domains(self):
        """Rendered sprint includes the shared file so LLM can detect overlap."""
        content = self._get_rendered_sprint(_multi_story_sprint_overlapping_domains())
        # Both stories reference src/shared/utils.py
        self.assertIn("src/shared/utils.py", content)

    def test_rendered_sprint_empty_domains_visible(self):
        """Stories with empty file domains render without file domain section."""
        content = self._get_rendered_sprint(_multi_story_sprint_no_domains())
        # Stories should be present
        self.assertIn("Feature A", content)
        self.assertIn("Feature B", content)


class TestPreloadE2EPipeline(_IntegrationTestCase):
    """Full E2E: init SMM, seed sprint, run preload, verify output paths."""

    def test_full_pipeline_with_smm_and_sprint(self):
        """Complete pipeline: SMM + sprint -> preload outputs both paths."""
        # Seed SMM
        write_smm_fixture(
            self.smm_dir,
            intent=[("Build auth system", "goal")],
            constraints=[("TDD always", "convention")],
        )
        # Seed sprint
        (self.smm_dir / "sprint.json").write_text(_multi_story_sprint_worktree())
        # Run preload
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        # Verify all expected outputs
        output = result.stdout
        self.assertIn("SMM_DIR=", output)
        self.assertIn("SMM_FILE=", output)
        self.assertIn("SPRINT_FILE=", output)

        # Verify SMM_DIR matches the test SMM dir
        smm_dir_val = _extract_preload_var(output, "SMM_DIR")
        self.assertEqual(smm_dir_val, str(self.smm_dir))

    def test_full_pipeline_smm_only_no_sprint(self):
        """Pipeline with SMM but no sprint -> SMM paths only."""
        write_smm_fixture(
            self.smm_dir,
            wisdom=["Small commits"],
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)
        self.assertIn("SMM_FILE=", result.stdout)
        self.assertNotIn("SPRINT_FILE=", result.stdout)

    def test_preload_plan_only_no_sprint(self):
        """Plan file exists, no sprint -> PLAN_FILE= and SMM_DIR= but no SPRINT_FILE=.

        Verifies plan-primary semantics: plan file is the primary input for
        mode selection and does not depend on sprint data.
        """
        sprint_path = self.smm_dir / "sprint.json"
        if sprint_path.exists():
            sprint_path.unlink()

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        self.assertIn("SMM_DIR=", output)
        self.assertIn("PLAN_FILE=", output, "Plan file should be primary input")
        self.assertNotIn("SPRINT_FILE=", output, "No sprint -> no SPRINT_FILE")

        plan_path = _extract_preload_var(output, "PLAN_FILE")
        assert plan_path is not None, "PLAN_FILE= value missing"
        self.assertTrue(
            Path(plan_path).is_file(),
            f"PLAN_FILE should point to a readable file: {plan_path}",
        )

    def test_preload_plan_before_sprint_in_output(self):
        """PLAN_FILE= appears before SPRINT_FILE= in preload output.

        Verifies plan-primary ordering: plan is evaluated first as the
        primary input for mode selection.
        """
        (self.smm_dir / "sprint.json").write_text(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        plan_pos = output.find("PLAN_FILE=")
        sprint_pos = output.find("SPRINT_FILE=")
        self.assertGreaterEqual(plan_pos, 0, "PLAN_FILE= must be present")
        self.assertGreaterEqual(sprint_pos, 0, "SPRINT_FILE= must be present")
        self.assertLess(
            plan_pos,
            sprint_pos,
            "PLAN_FILE= should appear before SPRINT_FILE= (plan is primary)",
        )

    def test_preload_clears_assign_pending_marker(self):
        """Preload clears .assign-pending marker."""
        marker = self.smm_dir / ".assign-pending"
        marker.write_text("gate-id")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists(), ".assign-pending should be cleared")


class TestTeammateReviewCycleE2E(_IntegrationTestCase):
    """E2E: teammate stop gate enforces review cycle sequence."""

    def _stop_input(self, **overrides) -> dict:
        data = {
            "session_id": "t",
            "agent_id": "teammate-1",
            "agent_type": "xp-teammate",
            "cwd": str(self.tmpdir),
        }
        data.update(overrides)
        return data

    def test_full_review_cycle_sequence(self):
        """Walk through the 5-step stop gate sequence end-to-end."""
        import markers
        import teammate_stop_gate

        inp = self._stop_input()

        # Step 1: uncommitted changes, no review → block for /xp-simplify
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/xp-simplify", result)

        # Step 2: simplify done → block for /xp-quality-review
        markers.set_review_flag(self.smm_dir, "teammate-1", "simplify_done")
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/xp-quality-review", result)

        # Step 3: quality review done → block for /security-review
        markers.set_review_flag(self.smm_dir, "teammate-1", "quality_review_done")
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/security-review", result)

        # Step 4: security review done → block for commit
        markers.set_review_flag(self.smm_dir, "teammate-1", "security_review_done")
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("commit", result.lower())

        # Step 5: no uncommitted changes → stop allowed
        result = teammate_stop_gate.run(
            inp, smm_dir=self.smm_dir, has_uncommitted=False
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
