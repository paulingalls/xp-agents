#!/usr/bin/env python3
"""Tests for the `accept-env` CLI subcommands, which live in branching_cli_accept.py.

Subprocess style (the house norm for asserting stdout + exit code): invoke
`python3 branching.py --smm-dir <smm> accept-env <action> ...`. branching.py's
__main__ delegates to branching_cli.main(), which calls
branching_cli_accept.register() to attach this subparser tree. Each test builds a
FRESH per-test git repo + teammate worktree (HEAD-mutating cases must not leak
across tests).
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import acceptance_env
import branching
from _branching_fixtures import (
    GIT_ENV,
    create_teammate_worktree_with_commit,
    get_current_branch,
    get_head_sha,
    init_repo_with_ignored_worktrees,
    make_conflicted_merge,
)

_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")


class TestAcceptEnvCli(unittest.TestCase):
    def setUp(self):
        self._repo_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = self._repo_td.name
        init_repo_with_ignored_worktrees(self.repo)

        self._smm_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        # Nest the SMM dir so its parent is this test's unique temp — the
        # out-of-repo worktree base is `{smm}.parent/worktrees` (story-024) —
        # and pin SMM_DIR so the in-process create and the branching subprocess
        # resolve the SAME location (conftest strips it, so an unpinned in-process
        # read shells init.sh to the real project and collides across tests).
        smm_dir = Path(self._smm_td.name) / "smm"
        smm_dir.mkdir()
        self.smm = str(smm_dir)
        self._prev_smm = os.environ.get("SMM_DIR")
        os.environ["SMM_DIR"] = self.smm

    def tearDown(self):
        if self._prev_smm is None:
            os.environ.pop("SMM_DIR", None)
        else:
            os.environ["SMM_DIR"] = self._prev_smm
        self._repo_td.cleanup()
        self._smm_td.cleanup()

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=GIT_ENV, capture_output=True, text=True
        )

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, _SCRIPT, "--smm-dir", self.smm, "accept-env", *args],
            capture_output=True,
            text=True,
            env=GIT_ENV,
        )

    def test_prepare_detaches_to_tip_and_prints_base(self):
        wt = create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        tip = get_head_sha(wt)
        r = self._run("prepare", "--cwd", self.repo, "--story", "story-042")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "main")  # restore ref on stdout
        self.assertEqual(get_current_branch(self.repo), "HEAD")  # detached
        self.assertEqual(get_head_sha(self.repo), tip)

    def test_prepare_refuses_dirty_tree(self):
        create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        (Path(self.repo) / "dirty.txt").write_text("uncommitted")
        r = self._run("prepare", "--cwd", self.repo, "--story", "story-042")
        self.assertNotEqual(r.returncode, 0)
        # Explanatory message on stderr (not stdout) — a regression routing it
        # elsewhere or genericizing it would still leave a non-empty stderr.
        self.assertEqual(r.stdout.strip(), "")
        self.assertIn("dirty", r.stderr)
        self.assertEqual(get_current_branch(self.repo), "main")  # HEAD untouched

    def test_restore_returns_to_ref(self):
        create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        self._run("prepare", "--cwd", self.repo, "--story", "story-042")
        self.assertEqual(get_current_branch(self.repo), "HEAD")
        r = self._run("restore", "--cwd", self.repo, "--restore-ref", "main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(get_current_branch(self.repo), "main")

    def test_prepare_then_restore_roundtrip(self):
        create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        p = self._run("prepare", "--cwd", self.repo, "--story", "story-042")
        base = p.stdout.strip()
        self.assertEqual(get_current_branch(self.repo), "HEAD")
        self._run("restore", "--cwd", self.repo, "--restore-ref", base)
        self.assertEqual(get_current_branch(self.repo), "main")
        self.assertTrue(branching.is_worktree_clean(self.repo))

    def test_recover_from_detached_head(self):
        self._git("checkout", "--detach", get_head_sha(self.repo))
        r = self._run("recover", "--cwd", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "detached-HEAD")
        self.assertEqual(get_current_branch(self.repo), "main")
        # Interrupted state fully cleared — not merely back on a branch.
        self.assertIsNone(acceptance_env.detect_interrupted(self.repo))

    def test_recover_from_in_progress_merge(self):
        make_conflicted_merge(self.repo)
        r = self._run("recover", "--cwd", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "in-progress-merge")
        # Merge aborted, HEAD back on a normal branch, nothing left interrupted.
        self.assertNotEqual(get_current_branch(self.repo), "HEAD")
        self.assertIsNone(acceptance_env.detect_interrupted(self.repo))

    def test_restore_bad_ref_errors(self):
        r = self._run("restore", "--cwd", self.repo, "--restore-ref", "no-such-branch")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(r.stderr.strip())

    def test_bare_accept_env_errors(self):
        # nested subparser required=True → bare `accept-env` exits non-zero.
        r = self._run()
        self.assertNotEqual(r.returncode, 0)

    # ---- inspect (read-only preload snapshot) -----------------------------

    def test_inspect_prints_enriched_tsv_row(self):
        wt = create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        tip = get_head_sha(wt)
        r = self._run("inspect", "--cwd", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), f"story-042\t{wt}\t{tip}\tmain")

    def test_inspect_flags_dirty_main_state(self):
        (Path(self.repo) / "dirty.txt").write_text("uncommitted")
        r = self._run("inspect", "--cwd", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MAIN_STATE\tdirty", r.stdout)

    def test_inspect_interrupted_takes_precedence_over_dirty(self):
        make_conflicted_merge(self.repo)
        r = self._run("inspect", "--cwd", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MAIN_STATE\tin-progress-merge", r.stdout)
        self.assertNotIn("dirty", r.stdout)

    def test_inspect_omits_flag_when_clean_and_no_worktree(self):
        r = self._run("inspect", "--cwd", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
