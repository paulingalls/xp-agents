#!/usr/bin/env python3
"""Tests for WorktreeCreate hook: branch base customization.

Platform input: {session_id, transcript_path, cwd, hook_event_name, name}.
The hook generates worktree path under .claude/worktrees/<name> in repo root,
creates a branch worktree-<name> from the current branch (not origin/HEAD).
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import identity
import worktree
from _system_context_fixtures import valid_doc, write_doc
from conftest import _IntegrationTestCase, cleanup_test_worktrees

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"

# Real platform input format
_INPUT = {
    "session_id": "test",
    "transcript_path": "/tmp/transcript.jsonl",
    "cwd": "/repo",
    "hook_event_name": "WorktreeCreate",
    "name": "abc123",
}


class TestWorktreeCreate(unittest.TestCase):
    """WorktreeCreate hook creates worktree from current branch."""

    def setUp(self):
        import importlib

        import worktree_create

        importlib.reload(worktree_create)
        self.worktree_create = worktree_create

    def _run_hook(
        self,
        current: str,
        default: str,
        input_data=None,
    ) -> tuple[str, mock.MagicMock]:
        """Run hook with mocked branch detection. Returns (result, mock_run)."""
        data = input_data or _INPUT
        with (
            mock.patch.object(
                identity,
                "get_current_branch",
                return_value=current,
            ),
            mock.patch.object(
                self.worktree_create,
                "_get_default_branch",
                return_value=default,
            ),
            mock.patch.object(
                worktree,
                "resolve_git_root",
                return_value="/repo",
            ),
            mock.patch("subprocess.run") as mock_run,
            mock.patch("pathlib.Path.mkdir"),
            mock.patch.object(
                self.worktree_create._common,
                "resolve_smm_dir",
                return_value=None,
            ),
        ):
            result = self.worktree_create.run(data)
            return result, mock_run

    def test_creates_from_current_branch_when_not_default(self):
        """On feature/v2 with default=main, worktree branches from it."""
        result, mock_run = self._run_hook("feature/v2", "main")
        self.assertIn("abc123", result)
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[-1], "feature/v2")

    def test_creates_without_base_when_on_default(self):
        """On main with default=main, no base ref appended."""
        _, mock_run = self._run_hook("main", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            [
                "git",
                "worktree",
                "add",
                "-b",
                "worktree-abc123",
                "/repo/.claude/worktrees/abc123",
            ],
        )

    def test_handles_missing_remote_gracefully(self):
        """No origin/HEAD → empty default, no base ref appended."""
        _, mock_run = self._run_hook("feature/v2", "")
        cmd = mock_run.call_args[0][0]
        # Should NOT append feature/v2 — can't compare without default
        self.assertNotIn("feature/v2", cmd)

    def test_handles_detached_head(self):
        """Detached HEAD → empty current, no base ref appended."""
        _, mock_run = self._run_hook("", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(
            cmd,
            [
                "git",
                "worktree",
                "add",
                "-b",
                "worktree-abc123",
                "/repo/.claude/worktrees/abc123",
            ],
        )

    def test_returns_worktree_path(self):
        """run() returns the worktree path."""
        result, _ = self._run_hook("main", "main")
        self.assertEqual(result, "/repo/.claude/worktrees/abc123")

    def test_branch_name_includes_worktree_prefix(self):
        """Branch is named worktree-<name>."""
        _, mock_run = self._run_hook("main", "main")
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[4], "worktree-abc123")

    def test_fails_when_git_worktree_add_fails(self):
        """CalledProcessError propagates when git worktree add fails."""
        with (
            mock.patch.object(
                identity,
                "get_current_branch",
                return_value="v2",
            ),
            mock.patch.object(
                self.worktree_create,
                "_get_default_branch",
                return_value="main",
            ),
            mock.patch.object(
                worktree,
                "resolve_git_root",
                return_value="/repo",
            ),
            mock.patch("pathlib.Path.mkdir"),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(128, "git"),
            ),
            mock.patch.object(
                self.worktree_create._common,
                "resolve_smm_dir",
                return_value=None,
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            self.worktree_create.run(_INPUT)

    def test_git_stdout_suppressed(self):
        """git worktree add stdout is DEVNULL."""
        _, mock_run = self._run_hook("v2", "main")
        kwargs = mock_run.call_args[1]
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)

    def test_generates_name_when_missing(self):
        """Missing name field generates a uuid-based name."""
        data = {
            "session_id": "t",
            "cwd": "/repo",
            "hook_event_name": "WorktreeCreate",
        }
        result, mock_run = self._run_hook("main", "main", input_data=data)
        self.assertIn("/repo/.claude/worktrees/", result)
        cmd = mock_run.call_args[0][0]
        self.assertTrue(cmd[4].startswith("worktree-"))

    def test_worktree_path_under_claude_dir(self):
        """Worktree is created under .claude/worktrees/ in repo root."""
        result, _ = self._run_hook("main", "main")
        self.assertTrue(
            result.startswith("/repo/.claude/worktrees/"),
        )


class _ProvisionsTestCase(_IntegrationTestCase):
    """Shared setup: a real git repo + real SMM dir the hook can bootstrap from."""

    def tearDown(self):
        cleanup_test_worktrees(self.tmpdir, prefix="worktree-")
        super().tearDown()

    def declare_bootstrap(self, command: str) -> None:
        """Declare `stack.worktree_bootstrap` in this repo's system_context."""
        doc = valid_doc()
        doc["stack"]["worktree_bootstrap"] = command
        write_doc(self.smm_dir, doc)

    def _run(self, name: str) -> str:
        """Run the real (unmocked) hook, with $SMM_DIR pinned to this test's SMM."""
        import importlib

        import worktree_create

        importlib.reload(worktree_create)
        with mock.patch.dict(os.environ, {"SMM_DIR": str(self.smm_dir)}):
            return worktree_create.run(
                {
                    "session_id": "test",
                    "cwd": str(self.tmpdir),
                    "hook_event_name": "WorktreeCreate",
                    "name": name,
                }
            )


class TestWorktreeCreateRunsDeclaredBootstrap(_ProvisionsTestCase):
    """AC1: a declared bootstrap command runs in the newly created worktree."""

    def test_declared_command_effect_is_observable_in_the_worktree(self):
        self.declare_bootstrap("echo provisioned > generated.txt")

        wt_path = self._run("worktree-story-011-provisions")

        artifact = Path(wt_path) / "generated.txt"
        self.assertTrue(
            artifact.is_file(),
            f"bootstrap must have run in the new worktree {wt_path}",
        )
        self.assertEqual(artifact.read_text().strip(), "provisioned")


class TestWorktreeCreateNoBootstrapIsUnchanged(_ProvisionsTestCase):
    """AC2: no declared bootstrap -> behavior unchanged, nothing runs/fails."""

    def test_no_worktree_bootstrap_field_is_a_no_op(self):
        write_doc(self.smm_dir, valid_doc())

        wt_path = self._run("worktree-story-011-noop")

        self.assertTrue(Path(wt_path).is_dir())
        self.assertFalse((Path(wt_path) / "generated.txt").exists())

    def test_no_system_context_is_a_no_op(self):
        (self.smm_dir / "system_context.json").unlink(missing_ok=True)

        wt_path = self._run("worktree-story-011-nosmm")

        self.assertTrue(Path(wt_path).is_dir())


class TestWorktreeCreateBootstrapFailsLoud(_ProvisionsTestCase):
    """AC3: a non-zero bootstrap fails loud and leaves the worktree standing."""

    def test_nonzero_exit_raises_and_worktree_stands(self):
        self.declare_bootstrap("echo half-done > partial.txt; exit 1")
        name = "worktree-story-011-fail"

        with self.assertRaises(SystemExit):
            self._run(name)

        wt = worktree.worktree_path(name, str(self.tmpdir))
        self.assertTrue(wt.is_dir(), "worktree must be left standing for inspection")
        self.assertTrue(
            (wt / "partial.txt").is_file(),
            "the partial bootstrap's output must survive for diagnosis",
        )


class TestWorktreeCreateE2E(_ProvisionsTestCase):
    """E2E AC: the real hook script (run through __main__) provisions the
    worktree end-to-end -- not create_worktree/run_bootstrap called directly.
    """

    def test_running_the_hook_as_a_subprocess_provisions_the_worktree(self):
        self.declare_bootstrap("echo provisioned > generated.txt")
        name = "worktree-story-011-e2e"
        payload = json.dumps(
            {
                "session_id": "test",
                "cwd": str(self.tmpdir),
                "hook_event_name": "WorktreeCreate",
                "name": name,
            }
        )
        env = {**os.environ, "SMM_DIR": str(self.smm_dir)}

        result = subprocess.run(
            [sys.executable, str(_SCRIPTS_DIR / "worktree_create.py")],
            input=payload,
            cwd=str(self.tmpdir),
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        wt_path = result.stdout.strip()
        artifact = Path(wt_path) / "generated.txt"
        self.assertTrue(
            artifact.is_file(),
            f"declared bootstrap did not run in {wt_path}: {result.stderr}",
        )
        self.assertEqual(artifact.read_text().strip(), "provisioned")


if __name__ == "__main__":
    unittest.main()
