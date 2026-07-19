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
from _branching_fixtures import (
    GIT_ENV,
    append_commit,
    init_repo,
    write_system_context,
)
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


class TestProseAboutADeleteIsNotADelete(_BranchDeleteGateCase):
    """A gate that refuses a commit over what its MESSAGE says is how people
    learn to route around gates -- story_done_gate's _MARK_DONE_RE carries the
    same scar, and this is the same class arriving by a different door: the
    branch name inside a quoted argument is TEXT, not an invocation."""

    def _run_unblocked(self, cmd: str) -> None:
        """`run` must not RAISE. It may still return an advisory string from an
        unrelated gate (committing on main nudges about branching), so asserting
        None here would pin a neighbour's behavior instead of this gate's."""
        try:
            self._run(cmd)
        except _common.BlockedError as blocked:
            self.fail(f"prose about a delete must not block: {blocked}")

    def test_commit_message_naming_a_branch_delete_is_not_blocked(self):
        self._make_story_branch()
        self._seed_sprint()

        # The literal shape of this sprint's OWN history: the commit that adds
        # the refusal documents the command it refuses.
        self._run_unblocked(
            f'git commit -m "[story-003] Refuse raw git branch -D {_STORY_BRANCH}"'
        )

    def test_single_quoted_message_naming_a_delete_is_not_blocked(self):
        self._make_story_branch()
        self._seed_sprint()

        self._run_unblocked(
            f"git commit -m 'chore: stop git branch -D {_STORY_BRANCH}'"
        )

    def test_heredoc_message_naming_a_delete_is_not_blocked(self):
        """A heredoc body is data the shell hands the command, not a command."""
        self._make_story_branch()
        self._seed_sprint()

        heredoc = (
            "git commit -F- <<'EOF'\nchore: stop this\n\n"
            f"git branch -D {_STORY_BRANCH}\nEOF"
        )
        self._run_unblocked(heredoc)

    def test_an_echo_describing_the_delete_is_not_blocked(self):
        self._make_story_branch()
        self._seed_sprint()

        self.assertIsNone(self._run(f'echo "run git branch -D {_STORY_BRANCH}"'))

    def test_a_quoted_branch_name_on_a_REAL_delete_still_blocks(self):
        """The inverse guard: dropping quoted text must not drop the argument
        of an actual delete -- quoting a branch name is ordinary shell."""
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f'git branch -D "{_STORY_BRANCH}"')

    def test_a_real_delete_chained_after_a_commit_that_mentions_it_blocks(self):
        """Prose in one segment must not blind the gate to a delete in the next."""
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(
                f'git commit -m "mentions git branch -D {_STORY_BRANCH}" '
                f"&& git branch -D {_STORY_BRANCH}"
            )


class TestDeleteIsJudgedInTheTargetedRepo(_BranchDeleteGateCase):
    """`git -C <dir>` retargets the REPO, so the merge proof must be evaluated
    there. Recognizing the `-C` form and then evaluating it against the hook's
    own cwd is worse than not recognizing it: the branch is absent HERE, and
    absence is exactly what this gate treats as proof of a merge."""

    def setUp(self):
        super().setUp()
        # A SECOND clone -- the repo the delete actually targets. self.repo,
        # where the hook runs, has never heard of its story branch.
        self._other_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._other_tmp.cleanup)
        self.other = str(Path(self._other_tmp.name) / "clone")
        # `git clone` does NOT copy the source repo's *local* config, so this
        # clone inherits no committer identity from init_repo. Every git call
        # here that creates a commit (notably the --no-ff merge below) must
        # therefore carry GIT_ENV explicitly — auto-detected identity is
        # rejected on CI runners whose guessed address ends in `.(none)`,
        # which surfaced as a `git merge` exit-128 that never reproduces on a
        # dev machine with a valid global git identity.
        subprocess.run(
            ["git", "clone", self.repo, self.other],
            capture_output=True,
            check=True,
            env=GIT_ENV,
        )

    def _make_other_story_branch(self) -> None:
        subprocess.run(
            ["git", "checkout", "-b", _STORY_BRANCH],
            cwd=self.other,
            capture_output=True,
            check=True,
            env=GIT_ENV,
        )
        append_commit(self.other, "story.txt")
        subprocess.run(
            ["git", "checkout", _BASE],
            cwd=self.other,
            capture_output=True,
            check=True,
            env=GIT_ENV,
        )

    def test_dash_c_delete_of_a_branch_unmerged_THERE_blocks(self):
        self._make_other_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git -C {self.other} branch -D {_STORY_BRANCH}")

    def test_dash_c_delete_of_a_branch_merged_THERE_passes(self):
        self._make_other_story_branch()
        subprocess.run(
            ["git", "merge", "--no-ff", _STORY_BRANCH, "-m", "Merge"],
            cwd=self.other,
            capture_output=True,
            check=True,
            env=GIT_ENV,
        )
        self._seed_sprint()

        self.assertIsNone(self._run(f"git -C {self.other} branch -D {_STORY_BRANCH}"))


class TestFailsClosedOnDishonestBase(_BranchDeleteGateCase):
    """AC6: sprint stage >= 2 but the sprint's branch cannot be resolved is
    the one dishonest state `resolve_story_base` reserves for None --
    matching story_done_gate's fail-closed contract on the merge gate."""

    def test_unresolvable_base_blocks_a_recognized_delete(self):
        self._make_story_branch()
        self._seed_sprint(branch_name="paulingalls/sprint-999-vanished")

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch -D {_STORY_BRANCH}")


class TestUnmergedStoryBranchRenameAwayRefused(_BranchDeleteGateCase):
    """`git branch -m/-M` renaming a story branch AWAY from its name makes
    it vanish exactly like a delete -- the mark-done gate must not read
    that absence as proof of a merge that never happened."""

    def test_two_arg_rename_away_with_dash_m_blocks(self):
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch -m {_STORY_BRANCH} {_STORY_BRANCH}-renamed")

    def test_two_arg_rename_away_with_dash_M_blocks(self):
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch -M {_STORY_BRANCH} {_STORY_BRANCH}-renamed")

    def test_long_form_move_flag_is_recognized(self):
        self._make_story_branch()
        self._seed_sprint()

        with self.assertRaises(_common.BlockedError):
            self._run(f"git branch --move {_STORY_BRANCH} {_STORY_BRANCH}-renamed")


class TestCurrentBranchRenameShorthandIsAnAcceptedGap(_BranchDeleteGateCase):
    """`git branch -m <new>` (one positional) names no source branch, so
    recognizing it would need live HEAD resolved at PreToolUse -- before the
    command runs. A chained `git checkout <story> && git branch -m <new>` would
    then resolve the BASE, not the story, and fail open silently. Rather than
    ship a leg reliable only when un-chained, this gate no-ops on the shorthand
    (documented, accepted gap) -- it never FALSELY blocks it either."""

    def _run_unblocked(self, cmd: str) -> None:
        try:
            self._run(cmd)
        except _common.BlockedError as blocked:
            self.fail(f"current-branch rename shorthand must not block: {blocked}")

    def test_current_branch_rename_shorthand_is_not_gated(self):
        self._make_story_branch()
        self._git("checkout", _STORY_BRANCH)
        self._seed_sprint()

        self._run_unblocked("git branch -m renamed-away")

    def test_chained_checkout_then_shorthand_rename_is_not_falsely_blocked(self):
        """The fail-open the removed leg pretended to close: PreToolUse fires
        before the command runs, so the in-command checkout is not yet in
        effect. Honestly a no-op, not a false block."""
        self._make_story_branch()
        self._seed_sprint()

        self._run_unblocked(
            f"git checkout {_STORY_BRANCH} && git branch -m renamed-away"
        )

    def test_malformed_three_positional_rename_is_not_caught(self):
        """`git branch -m OLD NEW EXTRA` is a git usage error (too many args).
        The gate must not take the first positional as OLD and misdirect the
        user with a delete refusal -- let git report its own usage error."""
        self._make_story_branch()
        self._git("checkout", _STORY_BRANCH)
        self._seed_sprint()

        self._run_unblocked(f"git branch -m {_STORY_BRANCH} foo bar")


class TestMergedStoryBranchRenameAwayAllowed(_BranchDeleteGateCase):
    """A rename of a branch already merged into its base passes untouched,
    matching the delete path's merged-branch allowance."""

    def test_merged_branch_rename_away_passes(self):
        self._make_story_branch()
        self._git("merge", "--no-ff", _STORY_BRANCH, "-m", "Merge")
        self._seed_sprint()

        self.assertIsNone(
            self._run(f"git branch -m {_STORY_BRANCH} {_STORY_BRANCH}-renamed")
        )


class TestNonStoryBranchRenameAllowed(_BranchDeleteGateCase):
    """Renaming a non-story branch, or renaming INTO a story-shaped name,
    is never this gate's concern -- only the OLD name vanishing matters."""

    def test_free_branch_rename_passes(self):
        self._git("checkout", "-b", "some-feature")
        append_commit(self.repo, "feature.txt")
        self._git("checkout", _BASE)
        # Deliberately do NOT seed a sprint -- same reasoning as the delete
        # path's non-story-branch case.

        self.assertIsNone(self._run("git branch -m some-feature some-feature-v2"))

    def test_rename_into_a_story_shaped_name_passes(self):
        """The NEW name matching the story pattern must not trip the gate --
        only the branch that VANISHES (the OLD name) is this gate's concern."""
        self._git("checkout", "-b", "some-feature")
        append_commit(self.repo, "feature.txt")
        self._git("checkout", _BASE)

        self.assertIsNone(self._run(f"git branch -m some-feature {_STORY_BRANCH}"))


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
