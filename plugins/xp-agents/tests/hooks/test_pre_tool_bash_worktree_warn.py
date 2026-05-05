#!/usr/bin/env python3
"""Tests for the cd-worktree-git advisory warning in pre_tool_bash.

The `cd <worktree> && git ...` pattern poisons the orchestrator's cwd for
follow-up Stop/PostToolUse hooks (notably the trailer-extract that links
Resolves-Event IDs from the commit message). Doctrine alone hasn't worked —
agents repeatedly hit the trap. This adds a warn-only PreToolUse matcher
that explains the impact and the `git -C <path>` fix. Never blocks;
never raises.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import pre_tool_bash
from _common import BlockedError
from conftest import _HookTestCase, _make_bash_input


class TestWorktreePathFragmentConvention(_HookTestCase):
    """Pin the convention so other modules can reuse it without drift."""

    def test_worktree_path_fragment_value(self):
        self.assertEqual(pre_tool_bash.WORKTREE_PATH_FRAGMENT, ".claude/worktrees/")


class TestCdWorktreeGitWarn(_HookTestCase):
    """Warn-only matcher for `cd <worktree> && git (commit|add|merge|push)`."""

    def _run(self, command: str) -> str | None:
        return pre_tool_bash.run(
            _make_bash_input(command=command),
            smm_dir=self.smm_dir,
        )

    # ----- Positive matches: warning fires on every commit-producing verb ---

    def _assert_warns(self, command: str, *, must_contain: tuple[str, ...] = ()) -> str:
        result = self._run(command)
        assert result is not None, "expected an additionalContext warning"
        # Anchor on the warning's leading "Avoid `cd <worktree>" so the
        # assertion fails if a different matcher fires by coincidence.
        self.assertIn("Avoid `cd <worktree>", result)
        self.assertIn("git -C", result)
        for token in must_contain:
            self.assertIn(token, result)
        return result

    def test_cd_worktree_then_commit_warns(self):
        self._assert_warns(
            "cd .claude/worktrees/worktree-story-001 && git commit -m 'fix'",
            must_contain=("trailer",),
        )

    def test_cd_worktree_then_add_warns(self):
        self._assert_warns("cd .claude/worktrees/worktree-story-002 && git add foo.py")

    def test_cd_worktree_then_merge_warns(self):
        self._assert_warns(
            "cd .claude/worktrees/worktree-story-003 && git merge feature"
        )

    def test_cd_worktree_then_push_warns(self):
        self._assert_warns(
            "cd .claude/worktrees/worktree-story-004 && git push origin HEAD"
        )

    # ----- Chained intervening segments — common agent shape ---------------

    def test_cd_worktree_then_intervening_then_git_warns(self):
        """`cd <wt> && pytest && git commit` — common run-checks-then-commit shape."""
        self._assert_warns(
            "cd .claude/worktrees/worktree-story-001 && pytest && git commit -m 'fix'",
            must_contain=("trailer",),
        )

    def test_cd_worktree_with_multiple_intervening_warns(self):
        """Multiple intervening `&&` segments before the git op."""
        self._assert_warns(
            "cd .claude/worktrees/worktree-story-002 && pytest -n auto "
            "&& ruff check && git add ."
        )

    # ----- Critical: warn-only — never raises BlockedError ------------------

    def test_warn_only_does_not_block(self):
        """The advisory must never raise BlockedError (warn-only contract)."""
        try:
            self._run("cd .claude/worktrees/worktree-story-001 && git commit -m 'fix'")
        except BlockedError as e:
            self.fail(f"warn matcher must not raise BlockedError, got: {e}")

    # ----- Non-triggers ----------------------------------------------------

    def test_git_dash_C_does_not_warn(self):
        """`git -C <wt>` is the recommended form — must NOT trigger."""
        result = self._run(
            "git -C .claude/worktrees/worktree-story-001 commit -m 'fix'"
        )
        # No warning text from this matcher should appear
        if result is not None:
            self.assertNotIn("git -C", result)

    def test_cd_non_worktree_path_does_not_warn(self):
        """cd into a non-worktree path (e.g. /tmp) must NOT trigger."""
        result = self._run("cd /tmp/something && git commit -m 'fix'")
        if result is not None:
            self.assertNotIn("git -C", result)

    def test_bare_git_commit_does_not_warn(self):
        """Bare `git commit` (no cd) must NOT trigger this matcher."""
        result = self._run("git commit -m 'fix'")
        if result is not None:
            self.assertNotIn("git -C", result)

    def test_long_chain_without_terminal_git_does_not_warn(self):
        """20 && segments after cd-into-worktree, no terminal git op — must NOT
        match AND must complete promptly (guards against pathological regex
        backtracking on long agent-generated bash commands)."""
        chain = " && ".join(f"cmd{i}" for i in range(20))
        command = f"cd .claude/worktrees/worktree-x && {chain}"
        result = self._run(command)
        if result is not None:
            self.assertNotIn("git -C", result)


if __name__ == "__main__":
    import unittest

    unittest.main()
