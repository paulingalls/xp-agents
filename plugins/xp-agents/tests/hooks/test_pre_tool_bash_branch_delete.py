#!/usr/bin/env python3
"""Refuse a raw `git branch -d/-D` of a non-ancestor (genuinely unmerged)
story branch.

The mark-done merge gate (story_done_gate.merged_block) trusts branch
ABSENCE as proof of merge -- no delete path in this project deletes an
unmerged branch. A raw `git branch -D <story-branch>` at the shell is the
one hole in that invariant: it deletes an UNMERGED branch outright, and the
gate then reads the branch's absence as "merged" -- an unmerged story could
be marked done (debt 5b58ea07ec84). This suite locks the PreToolUse:Bash
refusal that closes it.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import pre_tool_bash
import sprint_store
from _branching_fixtures import append_commit, init_repo, write_system_context
from conftest import _HookTestCase, _make_bash_input

_BASE = "main"
_STORY_BRANCH = "paulingalls/story-003-branch-delete-refusal"


class _BranchDeleteGateCase(_HookTestCase):
    """A real git repo plus a sprint whose branch_name resolves the base."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self._tmp.name
        init_repo(self.repo)
        write_system_context(self.smm_dir, 2)

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, capture_output=True, check=True)

    def _make_story_branch(self, name: str = _STORY_BRANCH) -> None:
        """Cut `name` off HEAD with a commit the base does not have."""
        self._git("checkout", "-b", name)
        append_commit(self.repo, "story.txt")
        self._git("checkout", _BASE)

    def _seed_sprint(self, *, branch_name: str = _BASE) -> None:
        sprint_store.save_sprint(
            self.smm_dir,
            {
                "sprint_id": "sprint-001",
                "goal": "g",
                "started": "2026-04-22",
                "milestone": "test",
                "branch_name": branch_name,
                "stories": [],
            },
        )

    def _run(self, cmd: str, **overrides):
        return pre_tool_bash.run(
            _make_bash_input(command=cmd, cwd=self.repo, **overrides),
            smm_dir=self.smm_dir,
        )


class TestUnmergedStoryBranchDeleteRefused(_BranchDeleteGateCase):
    """AC1: a genuinely unmerged story branch cannot be raw-deleted."""

    def test_git_branch_dash_d_capital_blocks(self):
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch -D {_STORY_BRANCH}")

    def test_the_block_names_the_branch_and_the_honest_path(self):
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError) as caught:
            self._run(f"git branch -D {_STORY_BRANCH}")

        msg = str(caught.exception)
        self.assertIn(_STORY_BRANCH, msg)
        self.assertIn("delete_branch", msg)
        self.assertIn("/xp-story-close", msg)

    def test_lowercase_dash_d_is_also_recognized(self):
        """`-d` is not a safety net (upstream wins over the base) -- treat it
        identically to `-D` for detection; we do our own ancestry check."""
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch -d {_STORY_BRANCH}")

    def test_long_form_delete_flag_is_recognized(self):
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch --delete {_STORY_BRANCH}")

    def test_combined_short_flag_is_recognized(self):
        """`-Df` combines force with delete -- still a delete."""
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch -Df {_STORY_BRANCH}")

    def test_git_dash_c_prefix_is_tolerated(self):
        """Worktrees share refs -- `git -C <worktree> branch -D ...` guards
        the same object store as a bare `git branch -D` at the repo root."""
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git -C {self.repo} branch -D {_STORY_BRANCH}")


class TestMergedStoryBranchDeleteAllowed(_BranchDeleteGateCase):
    """AC2: a branch actually merged into its base passes untouched."""

    def test_merged_branch_delete_passes(self):
        self._make_story_branch()
        self._git("merge", "--no-ff", _STORY_BRANCH, "-m", "Merge")
        self._seed_sprint()

        self.assertIsNone(self._run(f"git branch -d {_STORY_BRANCH}"))


class TestAbsentStoryBranchDeleteAllowed(_BranchDeleteGateCase):
    """AC3: deleting an already-gone branch is a no-op for us."""

    def test_absent_branch_delete_passes(self):
        self._seed_sprint()  # _STORY_BRANCH was never created

        self.assertIsNone(self._run(f"git branch -D {_STORY_BRANCH}"))


class TestNonStoryBranchDeleteAllowed(_BranchDeleteGateCase):
    """AC4: free/plan/primary branches are never our concern."""

    def test_free_branch_delete_passes(self):
        self._git("checkout", "-b", "some-feature")
        append_commit(self.repo, "feature.txt")
        self._git("checkout", _BASE)
        # Deliberately do NOT seed a sprint -- a non-story branch must never
        # even reach branch_resolution, let alone need one to resolve.

        self.assertIsNone(self._run("git branch -D some-feature"))


class TestUnparseableDeleteIsNoOp(_BranchDeleteGateCase):
    """AC5: a branch name hidden behind a shell variable is invisible to a
    hook that only sees command text -- no-op, never a block."""

    def test_shell_variable_branch_name_passes(self):
        self._make_story_branch()
        self._seed_sprint()

        self.assertIsNone(self._run('git branch -D "$BR"'))


class TestFailsClosedOnDishonestBase(_BranchDeleteGateCase):
    """AC6: sprint stage >= 2 but the sprint's branch cannot be resolved is
    the one dishonest state `resolve_story_base` reserves for None --
    matching story_done_gate's fail-closed contract on the merge gate."""

    def test_unresolvable_base_blocks_a_recognized_delete(self):
        self._make_story_branch()
        self._seed_sprint(branch_name="paulingalls/sprint-999-vanished")

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch -D {_STORY_BRANCH}")


class TestXpAgentBypass(_BranchDeleteGateCase):
    """AC7: xp-agents are never gated -- `run` returns before this check for
    any agent_type starting with `xp-` (close-path delete_branch calls prove
    the merge themselves)."""

    def test_xp_agent_deleting_unmerged_branch_is_not_gated(self):
        self._make_story_branch()
        self._seed_sprint()

        self.assertIsNone(
            self._run(f"git branch -D {_STORY_BRANCH}", agent_type="xp-story-close")
        )


if __name__ == "__main__":
    unittest.main()
