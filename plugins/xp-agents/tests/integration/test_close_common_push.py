#!/usr/bin/env python3
"""close_common.py `push` relocation for teammate stories.

A teammate story branch is held by its `.claude/worktrees/worktree-story-NNN`
worktree, which by v3.9.0 design has NO installed deps (node_modules/.env/e2e).
If /xp-story-close pushes from that worktree, the project's pre-push hook fires
THERE and crashes with ERR_MODULE_NOT_FOUND. So `push` relocates: it detaches
the MAIN checkout (which has the installed deps) onto the story tip, pushes
(the hook runs with deps, against the story's code), then restores the main
checkout to its base — reusing acceptance_env's Mechanism A primitives.

Solo stories (the branch is checked out in the push cwd) push directly — no
detach, zero behavior change. Detection: the branch is held elsewhere iff the
push cwd's current branch != the branch being pushed.
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

from _bases import _PLUGIN_ROOT
from _branching_fixtures import (
    GIT_ENV,
    add_bare_remote,
    create_teammate_worktree_with_commit,
    get_current_branch,
    get_head_sha,
    init_repo,
    init_repo_with_ignored_worktrees,
    remote_has_branch,
)

_CLOSE_COMMON = _PLUGIN_ROOT / "scripts" / "close_common.py"


def _push(cwd: str, branch: str, smm: str | None = None) -> subprocess.CompletedProcess:
    argv = [
        sys.executable,
        str(_CLOSE_COMMON),
        "push",
        "--cwd",
        cwd,
        "--branch",
        branch,
    ]
    if smm is not None:
        argv += ["--smm-dir", smm]
    return subprocess.run(argv, capture_output=True, text=True)


def _merge(
    cwd: str, source: str, target: str, smm: str | None = None
) -> subprocess.CompletedProcess:
    argv = [
        sys.executable,
        str(_CLOSE_COMMON),
        "merge",
        "--cwd",
        cwd,
        "--source",
        source,
        "--target",
        target,
    ]
    if smm is not None:
        argv += ["--smm-dir", smm]
    return subprocess.run(argv, cwd=cwd, env=GIT_ENV, capture_output=True, text=True)


def _recording_pre_push_hook(repo: str, marker: Path) -> None:
    """Install a pre-push hook that records `pwd -P` + HEAD then allows the push.

    Two lines land in the marker: the physical cwd the hook fired in (proves
    main-checkout vs worktree) and the HEAD sha at fire time (proves the
    working tree was the story tip).
    """
    hook = Path(repo) / ".git" / "hooks" / "pre-push"
    hook.write_text(
        f'#!/bin/sh\n{{ pwd -P; git rev-parse HEAD; }} > "{marker}"\nexit 0\n'
    )
    hook.chmod(0o755)


def _blocking_pre_push_hook(repo: str) -> None:
    """Install a pre-push hook that fails (simulates a red acceptance gate)."""
    hook = Path(repo) / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)


def _base_destroying_pre_push_hook(repo: str, base: str) -> None:
    """Install a pre-push hook that allows the push but deletes the base branch.

    The main checkout is detached during the push, so the base branch is not
    checked out anywhere and can be deleted here. By the time the relocate's
    `finally` restores, `git checkout <base>` fails — exercising the
    restore-failure hardening path.
    """
    hook = Path(repo) / ".git" / "hooks" / "pre-push"
    hook.write_text(f"#!/bin/sh\ngit branch -D {base}\nexit 0\n")
    hook.chmod(0o755)


class TestCloseCommonPushRelocate(unittest.TestCase):
    """Teammate story: push relocates to the main checkout via accept-env."""

    def setUp(self):
        self._repo_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = self._repo_td.name
        init_repo_with_ignored_worktrees(self.repo)
        self._smm_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.smm = self._smm_td.name
        add_bare_remote(self.repo)
        # The bare remote and the test's hook marker live inside the repo dir;
        # exclude them so they don't read as an "untracked → dirty" main tree
        # and trip the relocate's clean-tree precondition (mirrors
        # test_branching_push._setup_repo).
        (Path(self.repo) / ".git" / "info" / "exclude").write_text(
            "remote.git/\nhook_record\n"
        )
        # Teammate worktree with a real commit; its branch (held by the
        # worktree) is `worktree-story-042`, and the main checkout stays on
        # `main` (the story base).
        self.wt = create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        self.branch = get_current_branch(self.wt)
        self.tip = get_head_sha(self.wt)
        self.addCleanup(self._repo_td.cleanup)
        self.addCleanup(self._smm_td.cleanup)

    def test_relocates_push_to_main_checkout(self):
        marker = Path(self.repo) / "hook_record"
        _recording_pre_push_hook(self.repo, marker)
        result = _push(self.repo, self.branch, self.smm)
        self.assertEqual(result.returncode, 0, result.stderr)
        # The branch reached origin.
        self.assertTrue(remote_has_branch(self.repo, self.branch))
        # The hook fired in the MAIN checkout (not the worktree) against the
        # story tip.
        self.assertTrue(marker.exists(), "pre-push hook never fired")
        fired_cwd, fired_head = marker.read_text().splitlines()
        self.assertEqual(fired_cwd, os.path.realpath(self.repo))
        self.assertEqual(fired_head, self.tip)
        # The main checkout is restored to its base branch — not left detached.
        self.assertEqual(get_current_branch(self.repo), "main")

    def test_dirty_main_refuses_and_leaves_tree_untouched(self):
        (Path(self.repo) / "base.txt").write_text("orchestrator scratch\n")
        result = _push(self.repo, self.branch, self.smm)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(remote_has_branch(self.repo, self.branch))
        self.assertEqual(get_current_branch(self.repo), "main")
        self.assertEqual(
            (Path(self.repo) / "base.txt").read_text(), "orchestrator scratch\n"
        )

    def test_push_failure_restores_main(self):
        _blocking_pre_push_hook(self.repo)
        result = _push(self.repo, self.branch, self.smm)
        self.assertNotEqual(result.returncode, 0)
        # Even though the push was rejected by the hook, the main checkout must
        # be restored to its base — never left detached on the story tip.
        self.assertEqual(get_current_branch(self.repo), "main")

    def test_relocate_requires_smm_dir(self):
        # Without --smm-dir the relocate can't resolve the base ref → refuse.
        result = _push(self.repo, self.branch, smm=None)
        self.assertNotEqual(result.returncode, 0)

    def test_pre_detached_main_heals_then_relocates(self):
        # A prior crashed relocate can leave the main checkout detached. The
        # discriminator (current_branch != branch) still routes to relocate,
        # and acceptance_env.recover() HEALS the detached HEAD back to the base
        # before re-detaching — so the relocate succeeds AND restores to base.
        subprocess.run(
            ["git", "checkout", "--detach", "HEAD"],
            cwd=self.repo,
            env=GIT_ENV,
            capture_output=True,
            check=True,
        )
        self.assertEqual(get_current_branch(self.repo), "HEAD")  # confirm detached
        marker = Path(self.repo) / "hook_record"
        _recording_pre_push_hook(self.repo, marker)
        result = _push(self.repo, self.branch, self.smm)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(remote_has_branch(self.repo, self.branch))
        # recover() healed the pre-detached main; restore returns it to base.
        self.assertEqual(get_current_branch(self.repo), "main")

    def test_restore_failure_after_push_fails_loud_non_zero(self):
        # Push SUCCEEDS but the base branch vanishes before the finally restore.
        # The relocate must not emit a bare traceback or a silent rc=0 with main
        # detached — it surfaces a loud, actionable error and returns non-zero.
        _base_destroying_pre_push_hook(self.repo, "main")
        result = _push(self.repo, self.branch, self.smm)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("FAILED to restore", result.stderr)
        self.assertIn("git -C", result.stderr)
        # The push itself reached origin (it happened before restore failed).
        self.assertTrue(remote_has_branch(self.repo, self.branch))


class TestCloseCommonPushSolo(unittest.TestCase):
    """Solo story (or sprint/plan/free close): the branch is checked out in
    the push cwd → push directly, no detach, no --smm-dir needed."""

    def setUp(self):
        self._repo_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = self._repo_td.name
        init_repo(self.repo)
        add_bare_remote(self.repo)
        subprocess.run(
            ["git", "checkout", "-b", "story-solo"],
            cwd=self.repo,
            env=GIT_ENV,
            capture_output=True,
            check=True,
        )
        (Path(self.repo) / "f.txt").write_text("solo\n")
        subprocess.run(
            ["git", "add", "f.txt"], cwd=self.repo, env=GIT_ENV, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "solo work"],
            cwd=self.repo,
            env=GIT_ENV,
            capture_output=True,
            check=True,
        )
        self.addCleanup(self._repo_td.cleanup)

    def test_solo_pushes_directly_no_detach(self):
        result = _push(self.repo, "story-solo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(remote_has_branch(self.repo, "story-solo"))
        # No detach: HEAD stays on the story branch.
        self.assertEqual(get_current_branch(self.repo), "story-solo")

    def test_no_remote_skips(self):
        # Drop the remote → push skips (no detach, no error).
        subprocess.run(
            ["git", "remote", "remove", "origin"],
            cwd=self.repo,
            capture_output=True,
            check=True,
        )
        result = _push(self.repo, "story-solo")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped", result.stdout)


class TestCloseCommonMergeRepushWorktree(unittest.TestCase):
    """cmd_merge re-pushes <source> with --no-verify before merging (story-001).

    Close-time fixes (Step 4b validate-and-fix, Step 5c "fix now") land on
    <source> AFTER Step 2's push, so without a pre-merge re-push the PR record is
    permanently stale relative to what merged. cmd_merge re-pushes <source>
    before the merge, when a remote exists.

    --no-verify is deliberate: at story-close cmd_merge runs from the ORCHESTRATOR
    checkout (on the sprint base) while <source> is the teammate's STORY branch,
    so a pre-push hook would test the WRONG tree — proves nothing, costs minutes,
    and FAILS on a red base, leaving the PR stale in exactly the case this fixes.
    The identical commits already passed a verified pre-push at Step 2 and are
    verified again by cmd_merge's TARGET push (right tree).
    """

    def setUp(self):
        self._repo_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = self._repo_td.name
        init_repo_with_ignored_worktrees(self.repo)
        add_bare_remote(self.repo)
        (Path(self.repo) / ".git" / "info" / "exclude").write_text("remote.git/\n")
        # Teammate worktree holds the story branch; the main checkout stays on
        # `main` (the story base) — the orchestrator-at-story-close shape.
        self.wt = create_teammate_worktree_with_commit(self.repo, "story-042", GIT_ENV)
        self.branch = get_current_branch(self.wt)
        self.addCleanup(self._repo_td.cleanup)

    def test_merge_repushes_source_with_no_verify(self):
        # A pre-push hook that FAILS only for the source ref. --no-verify bypasses
        # it, so <source> reaches origin; a plain push would be blocked and the
        # branch would never arrive. The target push (main, no --no-verify) still
        # fires the hook and exits 0. <source> is worktree-held, so cmd_merge's
        # post-merge delete is skipped and the re-pushed ref survives to observe.
        hook = Path(self.repo) / ".git" / "hooks" / "pre-push"
        hook.write_text(
            f'#!/bin/sh\nif grep -q "{self.branch}"; then exit 1; fi\nexit 0\n'
        )
        hook.chmod(0o755)
        result = _merge(self.repo, self.branch, "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        # <source> reached origin — ONLY possible if the re-push used --no-verify
        # (the source-ref hook would have blocked a plain push).
        self.assertTrue(
            remote_has_branch(self.repo, self.branch),
            "source must be re-pushed to origin with --no-verify before merge",
        )

    def test_no_remote_skips_repush(self):
        # No remote → no re-push attempt, no warning, merge still succeeds.
        subprocess.run(
            ["git", "remote", "remove", "origin"],
            cwd=self.repo,
            capture_output=True,
            check=True,
        )
        result = _merge(self.repo, self.branch, "main")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("re-push", result.stderr.lower())


class TestCloseCommonMergeRepushFailure(unittest.TestCase):
    """A re-push failure warns loudly but does NOT abort the merge (story-001).

    The merge is the truth; a stale PR is a record problem, not a correctness
    one. Reproduces the known residual: a close-time amend/rebase makes the
    re-push non-fast-forward, so it warns and the PR stays stale — acceptable.
    """

    def setUp(self):
        self._repo_td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.repo = self._repo_td.name
        init_repo(self.repo)
        add_bare_remote(self.repo)
        (Path(self.repo) / ".git" / "info" / "exclude").write_text("remote.git/\n")

        def _g(*args: str, check: bool = True) -> subprocess.CompletedProcess:
            return subprocess.run(
                ["git", *args],
                cwd=self.repo,
                env=GIT_ENV,
                capture_output=True,
                text=True,
                check=check,
            )

        _g("checkout", "-b", "story-src")
        (Path(self.repo) / "f.txt").write_text("v1\n")
        _g("add", "f.txt")
        _g("commit", "-m", "story work")
        # Step 2's push: the PR head as of push time.
        _g("push", "-u", "origin", "story-src")
        # A close-time amend diverges local story-src from its pushed remote ref,
        # so the pre-merge re-push is non-fast-forward and fails.
        (Path(self.repo) / "f.txt").write_text("v2 (close-time fix)\n")
        _g("commit", "-a", "--amend", "-m", "story work (amended at close)")
        _g("checkout", "main")
        self.addCleanup(self._repo_td.cleanup)

    def test_repush_failure_warns_but_does_not_abort(self):
        result = _merge(self.repo, "story-src", "main")
        # Warn-don't-abort: the merge still lands, rc is 0.
        self.assertEqual(result.returncode, 0, result.stderr)
        stderr = result.stderr.lower()
        self.assertIn("re-push", stderr)
        self.assertIn("stale", stderr)
        # The merge actually happened on main.
        log = subprocess.run(
            ["git", "log", "--merges", "--oneline"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertIn("story-src", log.stdout)


if __name__ == "__main__":
    unittest.main()
