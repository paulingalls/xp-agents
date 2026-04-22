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
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _IntegrationTestCase,
    _s,
    _sprint_json,
    cleanup_test_worktrees,
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
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        super().tearDown()


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
                "ready",
                file_domain=["src/auth/register.py", "tests/test_register.py"],
            ),
            _s(
                "story-002",
                "Admin dashboard",
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
                "ready",
                file_domain=["src/models/user.py"],
            ),
            _s(
                "story-002",
                "User API",
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
                "ready",
                file_domain=["src/ui/header.py"],
            ),
            _s(
                "story-002",
                "Update readme",
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
            _s("story-001", "Feature A", "ready"),
            _s("story-002", "Feature B", "ready"),
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
                "ready",
                file_domain=["src/auth/login.py", "src/shared/utils.py"],
            ),
            _s(
                "story-002",
                "Password reset",
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

    def _seed_plan(self, content: str = "# Test Plan\n## Step 1\nDo things\n"):
        """Create a plan file and .last-plan-path marker."""
        plan_file = self.smm_dir / "test-plan.md"
        plan_file.write_text(content)
        (self.smm_dir / ".last-plan-path").write_text(str(plan_file))
        return plan_file

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
        self._seed_plan()
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
        self._seed_plan()
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

    def test_preload_outputs_plugin_root(self):
        """Preload outputs PLUGIN_ROOT for spawn_teammate.py."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLUGIN_ROOT=", result.stdout)


class TestTeammateReviewCycleE2E(_IntegrationTestCase):
    """E2E: teammate stop gate enforces review cycle sequence."""

    def _stop_input(self, **overrides) -> dict:
        data = {
            "session_id": "t",
            "cwd": str(self.tmpdir).rstrip("/") + "/.claude/worktrees/teammate-1/src",
        }
        data.update(overrides)
        return data

    def test_full_review_cycle_sequence(self):
        """Walk through the 5-step stop gate sequence end-to-end."""
        import markers
        import teammate_stop_gate

        inp = self._stop_input()

        # Step 1: uncommitted changes, no review → block for /simplify
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        self.assertIsNotNone(result)
        self.assertIn("/simplify", result)

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


def _claude_subprocess_mock(*, raise_error: bool = False):
    """Stub claude calls but pass git calls through to real subprocess."""
    original_run = subprocess.run

    def side_effect(cmd, **kwargs):
        if cmd and cmd[0] == "claude":
            if raise_error:
                raise subprocess.CalledProcessError(1, cmd)
            return subprocess.CompletedProcess(cmd, 0)
        return original_run(cmd, **kwargs)

    return side_effect


class TestSpawnTeammatePromptCleanup(_IntegrationTestCase):
    """spawn_teammate.main() deletes the prompt file after use."""

    def test_prompt_file_deleted_after_successful_spawn(self):
        import spawn_teammate

        prompt_file = Path(self.tmpdir) / "prompt.txt"
        prompt_file.write_text("test prompt")

        with (
            unittest.mock.patch.object(
                spawn_teammate,
                "create_worktree",
                return_value=str(self.tmpdir),
            ),
            unittest.mock.patch.object(
                subprocess,
                "run",
                side_effect=_claude_subprocess_mock(),
            ),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    "teammate-cleanup-ok",
                    "--smm-dir",
                    str(self.smm_dir),
                    "--prompt-file",
                    str(prompt_file),
                ]
            )

        self.assertFalse(prompt_file.exists())

    def test_prompt_file_deleted_after_failed_spawn(self):
        import spawn_teammate

        prompt_file = Path(self.tmpdir) / "prompt-fail.txt"
        prompt_file.write_text("test prompt")

        with (
            unittest.mock.patch.object(
                spawn_teammate,
                "create_worktree",
                return_value=str(self.tmpdir),
            ),
            unittest.mock.patch.object(
                subprocess,
                "run",
                side_effect=_claude_subprocess_mock(raise_error=True),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            spawn_teammate.main(
                [
                    "--name",
                    "teammate-cleanup-fail",
                    "--smm-dir",
                    str(self.smm_dir),
                    "--prompt-file",
                    str(prompt_file),
                ]
            )

        self.assertFalse(prompt_file.exists())


class TestCleanupTeammateE2E(_IntegrationTestCase):
    """Full lifecycle: create worktree, commit, merge, cleanup."""

    def test_full_cleanup_lifecycle(self):
        """Create worktree, merge branch, run cleanup, verify gone."""
        import markers
        import spawn_teammate

        name = "teammate-story-e2e"
        wt_path = spawn_teammate.create_worktree(name, str(self.tmpdir))
        self.assertTrue(Path(wt_path).is_dir())

        # Commit in the worktree
        (Path(wt_path) / "feature.txt").write_text("feature")
        subprocess.run(
            ["git", "add", "feature.txt"],
            cwd=wt_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add feature"],
            cwd=wt_path,
            capture_output=True,
            check=True,
        )

        # Create markers and report
        markers.write_review_cycle(self.smm_dir, name, {"simplify_done": True})
        report = self.smm_dir / f".teammate-report-{name}.txt"
        report.write_text("E2E report")

        # Merge into main branch
        subprocess.run(
            ["git", "merge", name, "--no-ff", "-m", "Merge"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # Run cleanup via subprocess
        result = subprocess.run(
            [
                "python3",
                str(self.scripts_dir / "cleanup_teammate.py"),
                "--name",
                name,
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(self.tmpdir),
            env=self._test_env,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stderr: {result.stderr}",
        )

        # Verify everything is cleaned up
        self.assertFalse(
            Path(wt_path).is_dir(),
            "Worktree dir should be removed",
        )
        branch_list = subprocess.run(
            ["git", "branch", "--list", name],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            branch_list.stdout.strip(),
            "",
            "Branch should be deleted",
        )
        rc_path = markers.marker_path(self.smm_dir, markers.REVIEW_CYCLE, name)
        self.assertFalse(rc_path.exists(), "Markers gone")
        self.assertFalse(report.exists(), "Report gone")

    def test_cleanup_rejects_unmerged(self):
        """Cleanup exits non-zero when branch has unmerged commits."""
        import spawn_teammate

        name = "teammate-story-unmerged"
        wt_path = spawn_teammate.create_worktree(name, str(self.tmpdir))

        # Commit in worktree but DON'T merge
        (Path(wt_path) / "wip.txt").write_text("wip")
        subprocess.run(
            ["git", "add", "wip.txt"],
            cwd=wt_path,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "WIP"],
            cwd=wt_path,
            capture_output=True,
            check=True,
        )

        result = subprocess.run(
            [
                "python3",
                str(self.scripts_dir / "cleanup_teammate.py"),
                "--name",
                name,
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
            cwd=str(self.tmpdir),
            env=self._test_env,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unmerged", result.stderr.lower())

        # Worktree should still exist
        self.assertTrue(Path(wt_path).is_dir())

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"


class TestAcceptPreloadTeammate(_IntegrationTestCase):
    """xp-accept preload detects teammate worktrees."""

    def setUp(self):
        super().setUp()
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [_s("story-001", "Feature", "in-progress")],
                sprint_id="sprint-017",
                started="2026-04-13",
            )
        )

    def test_preload_shows_teammate_worktrees(self):
        """Preload lists teammate worktrees when they exist."""
        import spawn_teammate

        name = "teammate-story-001"
        spawn_teammate.create_worktree(name, str(self.tmpdir))

        result = self._run_preload(_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TEAMMATE_WORKTREES", result.stdout)
        self.assertIn(name, result.stdout)

    def test_preload_no_worktrees_no_section(self):
        """Preload omits TEAMMATE_WORKTREES when none exist."""
        result = self._run_preload(_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("TEAMMATE_WORKTREES", result.stdout)

    def test_preload_outputs_plugin_root(self):
        """Preload outputs PLUGIN_ROOT for cleanup script access."""
        result = self._run_preload(_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLUGIN_ROOT=", result.stdout)

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
