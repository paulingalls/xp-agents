#!/usr/bin/env python3
"""Integration tests for xp-assign teammate workflow.

Split from test_assign.py — teammate lifecycle tests.
"""

import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _IntegrationTestCase,
    _s,
    _sprint_json,
    cleanup_test_worktrees,
)

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_ACCEPT_PRELOAD = _PLUGIN_ROOT / "skills" / "xp-accept" / "scripts" / "preload.sh"


def _run_with_tee_mock(*, raise_error: bool = False):
    """Stub run_with_tee so we don't actually launch claude in tests.

    Mirrors the success / CalledProcessError contract of the prior
    subprocess.run mock so existing test assertions hold.
    """

    def side_effect(cmd, **kwargs):
        if raise_error:
            raise subprocess.CalledProcessError(1, cmd)

    return side_effect


class TestTeammateReviewCycleE2E(_IntegrationTestCase):
    """E2E: teammate stop gate enforces review cycle sequence."""

    def _stop_input(self, **overrides) -> dict:
        data = {
            "session_id": "t",
            "cwd": str(self.tmpdir).rstrip("/")
            + "/.claude/worktrees/worktree-story-1/src",
        }
        data.update(overrides)
        return data

    def test_full_review_cycle_sequence(self):
        """Walk through the M-4 stop gate sequence end-to-end.

        Post-M-4 ladder: simplify → quality-review → commit. The per-commit
        security rung was removed when LLM /security-review moved to the
        close-skill Step 4.5 (cumulative diff at sprint/plan/free close).
        """
        import markers
        import teammate_stop_gate

        inp = self._stop_input()

        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertIn("/simplify", result)

        markers.set_review_flag(self.smm_dir, "worktree-story-1", "simplify_done")
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertIn("/xp-quality-review", result)

        markers.set_review_flag(self.smm_dir, "worktree-story-1", "quality_review_done")
        result = teammate_stop_gate.run(inp, smm_dir=self.smm_dir, has_uncommitted=True)
        assert result is not None
        self.assertIn("commit", result.lower())

        result = teammate_stop_gate.run(
            inp, smm_dir=self.smm_dir, has_uncommitted=False
        )
        self.assertIsNone(result)


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
                spawn_teammate,
                "run_with_tee",
                side_effect=_run_with_tee_mock(),
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
                spawn_teammate,
                "run_with_tee",
                side_effect=_run_with_tee_mock(raise_error=True),
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
        import markers
        import spawn_teammate

        name = "teammate-story-e2e"
        wt_path = spawn_teammate.create_worktree(name, str(self.tmpdir))
        self.assertTrue(Path(wt_path).is_dir())

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

        markers.write_review_cycle(self.smm_dir, name, {"simplify_done": True})
        report = self.smm_dir / f".teammate-report-{name}.txt"
        report.write_text("E2E report")

        subprocess.run(
            ["git", "merge", name, "--no-ff", "-m", "Merge"],
            cwd=self.tmpdir,
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
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

        self.assertFalse(Path(wt_path).is_dir())
        branch_list = subprocess.run(
            ["git", "branch", "--list", name],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(branch_list.stdout.strip(), "")
        rc_path = markers.marker_path(self.smm_dir, markers.REVIEW_CYCLE, name)
        self.assertFalse(rc_path.exists())
        self.assertFalse(report.exists())

    def test_cleanup_rejects_unmerged(self):
        import spawn_teammate

        name = "teammate-story-unmerged"
        wt_path = spawn_teammate.create_worktree(name, str(self.tmpdir))

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
        self.assertTrue(Path(wt_path).is_dir())

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


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
        import spawn_teammate

        name = "worktree-story-001"
        spawn_teammate.create_worktree(name, str(self.tmpdir))

        result = self._run_preload(_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TEAMMATE_WORKTREES", result.stdout)
        # Format (story-008): `story-id<TAB>abs-path` — tab makes the
        # split unambiguous when paths contain spaces (macOS user dirs).
        self.assertRegex(result.stdout, r"story-001\t/.*worktree-story-001")

    def test_preload_no_worktrees_no_section(self):
        result = self._run_preload(_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("TEAMMATE_WORKTREES", result.stdout)

    def test_preload_outputs_plugin_root(self):
        result = self._run_preload(_ACCEPT_PRELOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLUGIN_ROOT=", result.stdout)

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir)
        super().tearDown()


if __name__ == "__main__":
    unittest.main()
