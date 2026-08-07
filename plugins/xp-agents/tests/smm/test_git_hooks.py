#!/usr/bin/env python3
"""Tests for smm/git_hooks.py — shared git-hook detection primitives.

Two consumers compose these primitives differently:
- `seed_detect.has_git_hooks`: declared marker OR will_fire_hook OR
  content-sniff (intent-aware — "is this project hook-aware?")
- `close_review_support.pre_commit_hook_present`: will_fire_hook alone
  (strict — "will git actually run something on this commit?")

This file tests the primitives at their own level so coverage isn't only
exercised through one consumer's path, and pins the case that distinguishes
the two: a repo declaring a runner it never installed.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import git_hooks
import seed_detect


def _init_repo(td: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(td)], capture_output=True, check=True
    )


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)


class TestHasFrameworkMarker(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_marker_returns_false(self):
        self.assertFalse(git_hooks.has_framework_marker(str(self.tmpdir)))

    def test_lefthook_yml(self):
        (self.tmpdir / "lefthook.yml").touch()
        self.assertTrue(git_hooks.has_framework_marker(str(self.tmpdir)))

    def test_dotted_lefthook_yml(self):
        (self.tmpdir / ".lefthook.yml").touch()
        self.assertTrue(git_hooks.has_framework_marker(str(self.tmpdir)))

    def test_pre_commit_config(self):
        (self.tmpdir / ".pre-commit-config.yaml").touch()
        self.assertTrue(git_hooks.has_framework_marker(str(self.tmpdir)))

    def test_husky_pre_commit(self):
        (self.tmpdir / ".husky").mkdir()
        (self.tmpdir / ".husky" / "pre-commit").touch()
        self.assertTrue(git_hooks.has_framework_marker(str(self.tmpdir)))


class TestResolvedHooksDir(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_repo(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_when_no_override(self):
        self.assertEqual(
            git_hooks.resolved_hooks_dir(str(self.tmpdir)),
            self.tmpdir / ".git" / "hooks",
        )

    def test_absolute_override(self):
        custom = self.tmpdir / "custom-hooks"
        custom.mkdir()
        subprocess.run(
            ["git", "config", "core.hooksPath", str(custom)],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        self.assertEqual(git_hooks.resolved_hooks_dir(str(self.tmpdir)), custom)

    def test_relative_override_resolves_against_repo_root(self):
        rel = self.tmpdir / "relative-hooks"
        rel.mkdir()
        subprocess.run(
            ["git", "config", "core.hooksPath", "relative-hooks"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        self.assertEqual(
            git_hooks.resolved_hooks_dir(str(self.tmpdir)),
            self.tmpdir / "relative-hooks",
        )

    def test_returns_default_when_git_call_fails(self):
        """Missing git OR cwd outside a repo → fall back to <root>/.git/hooks
        without raising. Mirrors identity._git_config error tolerance."""
        from unittest.mock import patch

        with patch(
            "git_hooks.subprocess.run", side_effect=FileNotFoundError("git not found")
        ):
            self.assertEqual(
                git_hooks.resolved_hooks_dir(str(self.tmpdir)),
                self.tmpdir / ".git" / "hooks",
            )

    def test_tilde_in_override_is_expanded(self):
        with tempfile.TemporaryDirectory() as home:
            tilde_target = Path(home) / "dotfiles" / "hooks"
            tilde_target.mkdir(parents=True)
            subprocess.run(
                ["git", "config", "core.hooksPath", "~/dotfiles/hooks"],
                cwd=self.tmpdir,
                capture_output=True,
                check=True,
            )
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home
            try:
                self.assertEqual(
                    git_hooks.resolved_hooks_dir(str(self.tmpdir)), tilde_target
                )
            finally:
                if old_home is not None:
                    os.environ["HOME"] = old_home
                else:
                    del os.environ["HOME"]


class TestHasExecutableHook(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_repo(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_hooks_returns_false(self):
        self.assertFalse(git_hooks.has_executable_hook(str(self.tmpdir)))

    def test_executable_pre_commit(self):
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-commit")
        self.assertTrue(git_hooks.has_executable_hook(str(self.tmpdir)))

    def test_executable_pre_push(self):
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-push")
        self.assertTrue(git_hooks.has_executable_hook(str(self.tmpdir)))

    def test_non_executable_pre_commit_returns_false(self):
        hook = self.tmpdir / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n")
        # Don't chmod.
        self.assertFalse(git_hooks.has_executable_hook(str(self.tmpdir)))

    def test_executable_hook_in_a_linked_worktree(self):
        """A linked worktree's `.git` is a FILE, so `<root>/.git/hooks` names a
        path that never exists — yet the shared hooks fire on every commit made
        there. This is where the close skills actually run (teammate
        worktrees), so answering False here tells every teammate close that the
        merge runs no tests while lefthook is running them.
        """
        commit = subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@example.invalid",
                "-c",
                "user.name=t",
                "commit",
                "--allow-empty",
                "-m",
                "init",
            ],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(commit.returncode, 0, commit.stderr)
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-commit")
        worktree = self.tmpdir.parent / f"{self.tmpdir.name}-wt"
        result = subprocess.run(
            ["git", "worktree", "add", "-b", "wt", str(worktree)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            self.assertTrue((worktree / ".git").is_file())
            self.assertTrue(git_hooks.has_executable_hook(str(worktree)))
            self.assertTrue(git_hooks.will_fire_hook(str(worktree)))
        finally:
            shutil.rmtree(worktree, ignore_errors=True)

    def test_executable_in_core_hookspath_override(self):
        custom = self.tmpdir / "custom-hooks"
        custom.mkdir()
        _make_executable(custom / "pre-commit")
        subprocess.run(
            ["git", "config", "core.hooksPath", str(custom)],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        self.assertTrue(git_hooks.has_executable_hook(str(self.tmpdir)))


class TestWillFireHook(unittest.TestCase):
    """Strict: an executable hook in the resolved hooks dir → True.

    A framework marker does NOT count. A config file on disk declares that a
    runner would install a hook; it is not evidence git will fire one. The
    declared-intent question belongs to the consumer that wants it — see
    `seed_detect.has_git_hooks`.
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_repo(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_neither_returns_false(self):
        self.assertFalse(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_marker_alone_does_not_fire(self):
        """The whole defect: an uninstalled runner config fires nothing."""
        (self.tmpdir / "lefthook.yml").touch()
        self.assertFalse(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_executable_hook_alone_returns_true(self):
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-commit")
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_executable_pre_push_alone_returns_true(self):
        # Pre-push counts as evidence of git-hook usage; matches close-skill
        # preload semantics ("project will run something on commit OR push").
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-push")
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))


class TestAFailedGitCallDegradesToTheJoin(unittest.TestCase):
    """When git cannot be consulted, the answer silently becomes the join.

    Pinned because it is a real limitation, not a nicety: for a repo using
    `core.hooksPath` the plain join names a dir with no hook, so a failed
    call turns `present` into `absent` with no signal to anyone. That is
    fail-open for the close preloads (they emit extra guidance rather than
    block), which is why it degrades rather than raises — a hook that dies
    gates nothing at all.

    The trigger is what must stay out of reach: a 5s timeout was tripped by
    16-way parallel test runs, making a load spike look like a missing hook.
    `_GIT_TIMEOUT_S` guards a genuine hang, so it sits far above spawn
    latency. This test pins the DEGRADATION, so if the fallback ever grows a
    real "unknown" answer, it fails and asks to be reconsidered.
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_repo(self.tmpdir)
        self.override = self.tmpdir / "team-hooks"
        self.override.mkdir()
        _make_executable(self.override / "pre-commit")
        subprocess.run(
            ["git", "config", "core.hooksPath", str(self.override)],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_the_override_is_found_when_git_answers(self):
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_a_timeout_degrades_to_the_plain_join(self):
        from unittest.mock import patch

        with patch(
            "git_hooks.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=1),
        ):
            self.assertEqual(
                git_hooks.resolved_hooks_dir(str(self.tmpdir)),
                self.tmpdir / ".git" / "hooks",
            )

    def test_the_timeout_is_a_hang_guard_not_a_latency_bound(self):
        self.assertGreaterEqual(git_hooks._GIT_TIMEOUT_S, 30)


class TestNonRepoRootNeverBorrowsAncestorHooks(unittest.TestCase):
    """A directory that is not itself a repo has no hooks of its own.

    `git rev-parse --git-path hooks` answers about the repo it FINDS, walking
    up from cwd — so asked about a plain directory nested under a repo it
    reports the ancestor's hooks dir and exits 0. Answering that way makes
    both consumers describe a different repository than the one they were
    handed: seeding records hooks=true for a project under no version control
    of its own, and the close preloads report the gate present, suppressing
    the "this merge fires no project tests" block for a project that has no
    test gate at all.
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_repo(self.tmpdir)
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-commit")
        self.nested = self.tmpdir / "subproject"
        self.nested.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nested_non_repo_does_not_fire(self):
        self.assertFalse(git_hooks.will_fire_hook(str(self.nested)))

    def test_nested_non_repo_is_not_hook_aware(self):
        self.assertFalse(seed_detect.has_git_hooks(self.nested))

    def test_the_ancestor_itself_still_fires(self):
        """The guard rejects the borrow, not the detection."""
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))


class TestTheTwoConsumersDisagree(unittest.TestCase):
    """The declared-but-not-installed repo is the case the split exists for.

    On a repo carrying a runner config it never installed, the two answers must
    differ: nothing will fire, AND the project is still hook-aware.
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_repo(self.tmpdir)
        (self.tmpdir / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_strict_says_nothing_fires(self):
        self.assertFalse(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_intent_aware_still_says_hook_aware(self):
        self.assertTrue(seed_detect.has_git_hooks(self.tmpdir))

    def test_installing_the_hook_makes_them_agree(self):
        """The split is about the DECLARATION, not a blanket downgrade: once a
        hook is really wired up, both consumers say yes."""
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-commit")
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))
        self.assertTrue(seed_detect.has_git_hooks(self.tmpdir))


if __name__ == "__main__":
    unittest.main()
