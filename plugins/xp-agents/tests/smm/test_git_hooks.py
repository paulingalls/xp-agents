#!/usr/bin/env python3
"""Tests for smm/git_hooks.py — shared git-hook detection primitives.

Two consumers compose these primitives differently:
- `seed_smm.has_git_hooks`: will_fire_hook OR content-sniff (intent-aware)
- `close_review_support.pre_commit_hook_present`: will_fire_hook (strict)

This file tests the primitives at their own level so coverage isn't only
exercised through one consumer's path.
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
    """Composition: framework marker OR executable hook → True."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_repo(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_neither_returns_false(self):
        self.assertFalse(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_marker_alone_returns_true(self):
        (self.tmpdir / "lefthook.yml").touch()
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_executable_hook_alone_returns_true(self):
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-commit")
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))

    def test_executable_pre_push_alone_returns_true(self):
        # Pre-push counts as evidence of git-hook usage; matches close-skill
        # preload semantics ("project will run something on commit OR push").
        _make_executable(self.tmpdir / ".git" / "hooks" / "pre-push")
        self.assertTrue(git_hooks.will_fire_hook(str(self.tmpdir)))


if __name__ == "__main__":
    unittest.main()
