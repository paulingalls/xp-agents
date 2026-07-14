#!/usr/bin/env python3
"""Direct-import behavioral tests for branch_lifecycle.py.

Per Refactor Mode wisdom 144c2958330c: a NEW primitive module needs at
least one direct-import behavioral test even when extracted from
already-tested code. The shim-import test in test_branching.py covers
the backwards-compat re-export contract; this suite locks in the new
module as a primitive in its own right.

Existing branching.merge_branch / delete_branch coverage remains in
test_branching_lifecycle.py — duplicating those scenarios here is
unnecessary because the re-exports prove identity.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import branch_lifecycle
from _branching_fixtures import GIT_ENV, append_commit, get_current_branch, init_repo


def _checkout_new(cwd: str, name: str, base: str | None = None) -> None:
    cmd = ["git", "checkout", "-b", name]
    if base is not None:
        cmd.append(base)
    subprocess.run(cmd, cwd=cwd, capture_output=True, check=True)


def _checkout(cwd: str, name: str) -> None:
    subprocess.run(["git", "checkout", name], cwd=cwd, capture_output=True, check=True)


class TestIsMergedInto(unittest.TestCase):
    def test_ancestor_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            main = get_current_branch(td)
            _checkout_new(td, "feat")
            self.assertTrue(branch_lifecycle.is_merged_into(td, main, "feat"))

    def test_diverged_returns_false(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            _checkout_new(td, "feat")
            append_commit(td, "feat.txt")
            self.assertFalse(branch_lifecycle.is_merged_into(td, "feat", "main"))


class TestFastForwardIfSafe(unittest.TestCase):
    def test_fast_forwards_when_ancestor(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            _checkout_new(td, "topic")
            _checkout(td, "main")
            append_commit(td, "advance.txt")
            advanced_sha = subprocess.run(
                ["git", "rev-parse", "main"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            _checkout(td, "topic")

            branch_lifecycle._fast_forward_if_safe(td, "topic", "main")

            new_sha = subprocess.run(
                ["git", "rev-parse", "topic"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(new_sha, advanced_sha)

    def test_no_op_when_branch_has_unique_commits(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            _checkout_new(td, "topic")
            append_commit(td, "topic-only.txt")
            topic_sha = subprocess.run(
                ["git", "rev-parse", "topic"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            branch_lifecycle._fast_forward_if_safe(td, "topic", "main")

            after_sha = subprocess.run(
                ["git", "rev-parse", "topic"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(after_sha, topic_sha)


class TestMergeIntoTarget(unittest.TestCase):
    def test_no_ff_merge_lands_on_target(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            main = get_current_branch(td)
            _checkout_new(td, "paul/story-007-x")
            append_commit(td, "feature.txt")

            branch_lifecycle._merge_into_target(td, "paul/story-007-x", main)

            self.assertEqual(get_current_branch(td), main)
            log = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn("paul/story-007-x", log)


class TestIndexLockRetry(unittest.TestCase):
    """A transient `.git/index.lock` must not fail the merge on first contact.

    This is what bit story-005: a sibling teammate worktree held the lock for a
    moment, the merge failed, and the close carried on. The retry NARROWS that
    window -- it does not close it, and it is not the fix. The mark-done gate is
    the fix. This just stops the common case from ever reaching it.

    Asserted STRUCTURALLY with an injected clock: the retry's value is "it tried
    again and it backed off", and pinning that to wall-clock time would buy a slow,
    flaky test for no extra proof.
    """

    _LOCK_STDERR = (
        "fatal: Unable to create '/repo/.git/index.lock': File exists.\n\n"
        "Another git process seems to be running in this repository."
    )

    def _result(self, rc: int, stderr: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=["git"], returncode=rc, stderr=stderr)

    def test_retries_then_succeeds_and_backs_off(self):
        calls: list[list[str]] = []
        slept: list[float] = []
        results = [
            self._result(128, self._LOCK_STDERR),
            self._result(128, self._LOCK_STDERR),
            self._result(0),
        ]

        def fake_git(args, cwd):
            calls.append(args)
            return results[len(calls) - 1]

        with patch.object(branch_lifecycle, "_git", fake_git):
            r = branch_lifecycle._git_retry_on_lock(
                ["git", "merge"], "/repo", sleep=slept.append
            )

        self.assertEqual(r.returncode, 0)
        self.assertEqual(len(calls), 3, "it must actually retry, not just wait")
        self.assertEqual(len(slept), 2, "one backoff between each pair of attempts")
        self.assertLess(slept[0], slept[1], "the backoff must grow, not hammer")

    def test_a_real_conflict_is_NOT_retried(self):
        """The control, and the reason this helper is not a blanket git retry.

        Retrying a genuine failure would mask it -- a merge conflict is not going to
        resolve itself on the second try, and burning the backoff on it would turn a
        clear error into a slow, confusing one. Only the lock signature retries.
        """
        calls: list[list[str]] = []
        slept: list[float] = []

        def fake_git(args, cwd):
            calls.append(args)
            return self._result(1, "CONFLICT (content): Merge conflict in app.py")

        with patch.object(branch_lifecycle, "_git", fake_git):
            r = branch_lifecycle._git_retry_on_lock(
                ["git", "merge"], "/repo", sleep=slept.append
            )

        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(calls), 1, "a conflict must fail on the FIRST attempt")
        self.assertEqual(slept, [], "and must not burn the backoff")

    def test_a_lock_that_never_clears_gives_up_and_reports_the_failure(self):
        """Bounded. The lock holder may never let go, and an unbounded retry would
        hang the close instead of failing it -- so it gives up and hands the caller
        git's own stderr, which is what makes _merge_into_target exit non-zero."""
        calls: list[list[str]] = []

        def fake_git(args, cwd):
            calls.append(args)
            return self._result(128, self._LOCK_STDERR)

        with patch.object(branch_lifecycle, "_git", fake_git):
            r = branch_lifecycle._git_retry_on_lock(
                ["git", "merge"], "/repo", sleep=lambda _s: None
            )

        self.assertEqual(r.returncode, 128)
        self.assertIn("index.lock", r.stderr)
        self.assertEqual(len(calls), 3, "bounded attempts, not an unbounded spin")

    def test_the_merge_path_uses_the_retry(self):
        """The wiring. A retry helper nothing calls is decoration."""
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            main = get_current_branch(td)
            _checkout_new(td, "paul/story-x")
            append_commit(td, "f.txt")

            with patch.object(
                branch_lifecycle,
                "_git_retry_on_lock",
                wraps=branch_lifecycle._git_retry_on_lock,
            ) as spy:
                branch_lifecycle._merge_into_target(td, "paul/story-x", main)

            self.assertGreaterEqual(
                spy.call_count, 2, "checkout AND merge both go through it"
            )


class TestMergeBranch(unittest.TestCase):
    def test_delegates_to_merge_into_target(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            main = get_current_branch(td)
            _checkout_new(td, "paul/story-008-y")
            append_commit(td, "feat.txt")

            branch_lifecycle.merge_branch(td, "paul/story-008-y", main)

            self.assertEqual(get_current_branch(td), main)


class TestPushSourceNoVerify(unittest.TestCase):
    """The pre-merge re-push warns but NEVER raises — its whole contract is that
    a failed re-push cannot abort the merge that follows it."""

    def test_spawn_failure_warns_and_returns_instead_of_raising(self):
        """subprocess.run has no timeout here (a slow push must not raise), but it
        can still raise OSError/FileNotFoundError on a spawn failure. That must be
        swallowed into a warning, not propagated to abort cmd_merge before merge."""

        def boom(*a, **k):
            raise FileNotFoundError("git not on PATH")

        with patch.object(branch_lifecycle.subprocess, "run", boom):
            # Must not raise.
            branch_lifecycle.push_source_no_verify("/repo", "story-src")


class TestDeleteBranch(unittest.TestCase):
    def test_deletes_merged_branch(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            main = get_current_branch(td)
            _checkout_new(td, "paul/story-009-d")
            append_commit(td, "f.txt")
            _checkout(td, main)
            subprocess.run(
                ["git", "merge", "--no-ff", "paul/story-009-d", "-m", "merge"],
                cwd=td,
                capture_output=True,
                check=True,
                env=GIT_ENV,
            )

            self.assertTrue(branch_lifecycle.delete_branch(td, "paul/story-009-d"))

    def test_returns_false_for_unmerged_without_target(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            _checkout_new(td, "topic")
            append_commit(td, "uniq.txt")
            _checkout(td, "main")

            self.assertFalse(branch_lifecycle.delete_branch(td, "topic"))

    def test_force_deletes_when_merge_target_proves_safe(self):
        """Branch -d refusal triggers -D fallback only when proven merged
        into the supplied merge_target — locks in the worktree-teammate
        recovery path documented in branching.delete_branch."""
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            main = get_current_branch(td)
            _checkout_new(td, "paul/story-010-ff")
            append_commit(td, "ff.txt")
            _checkout(td, main)
            subprocess.run(
                ["git", "merge", "--no-ff", "paul/story-010-ff", "-m", "merge"],
                cwd=td,
                capture_output=True,
                check=True,
                env=GIT_ENV,
            )
            # Simulate the worktree-teammate state: the local branch is
            # merged into main but its tracking ref differs, which makes
            # `git branch -d` refuse. Easiest way to provoke -d refusal
            # without a remote: rewrite the branch ref to a different
            # commit that is still merged.
            subprocess.run(
                ["git", "update-ref", "refs/heads/paul/story-010-ff", "HEAD~1"],
                cwd=td,
                capture_output=True,
                check=True,
            )

            self.assertTrue(
                branch_lifecycle.delete_branch(
                    td, "paul/story-010-ff", merge_target=main
                )
            )


if __name__ == "__main__":
    unittest.main()
