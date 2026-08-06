#!/usr/bin/env python3
"""Tests for identity's git-state readers: get_current_branch, extract_story_id
and merge_in_progress.

Split from `test_identity.py` (582 lines). Both branch readers answer "which
story is this branch", which is a different question from "which agent am I" —
the branch is on disk, the agent identity is inferred from cwd and env.
`merge_in_progress` is the same KIND of read (a git-state fact about the
checkout, from the same `_git_stdout`), which is why it lives beside them
rather than in a second detector of its own.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import identity
from _branching_fixtures import (
    GIT_ENV,
    init_repo,
    init_repo_with_ignored_worktrees,
    make_conflicted_merge,
)


class TestGetCurrentBranch(unittest.TestCase):
    """get_current_branch returns branch name or empty string."""

    def test_returns_branch_in_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            result = identity.get_current_branch(td)
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 0)

    def test_returns_empty_on_invalid_dir(self):
        result = identity.get_current_branch("/nonexistent/path")
        self.assertEqual(result, "")


class TestExtractStoryId(unittest.TestCase):
    """extract_story_id parses `<user>/story-NNN-<slug>` branch names.

    Powers /xp-story-close's JIT-next gate (Step 7b worktree cleanup):
    given the just-closed CURRENT_BRANCH, return the story-NNN id so
    we can locate the matching teammate worktree. Returns None for
    branches that don't match the convention (free branches, plan
    branches, primary branches).
    """

    def test_user_prefix_with_slug(self):
        self.assertEqual(
            identity.extract_story_id("paul/story-001-jit-branches"),
            "story-001",
        )

    def test_user_prefix_no_slug(self):
        # Slug-less variants (e.g. older spawn_teammate output) still
        # match — the trailing hyphen + slug is optional.
        self.assertEqual(
            identity.extract_story_id("paul/story-042"),
            "story-042",
        )

    def test_three_digit_story_id(self):
        self.assertEqual(
            identity.extract_story_id("alice/story-100-feature"),
            "story-100",
        )

    def test_no_user_prefix(self):
        # Non-conforming branch — return None.
        self.assertIsNone(identity.extract_story_id("story-001-direct"))

    def test_free_branch(self):
        self.assertIsNone(
            identity.extract_story_id("paul/free-2026-04-30-jit-branches")
        )

    def test_plan_branch(self):
        self.assertIsNone(identity.extract_story_id("paul/plan-auth"))

    def test_primary_branch(self):
        self.assertIsNone(identity.extract_story_id("main"))

    def test_empty_string(self):
        self.assertIsNone(identity.extract_story_id(""))

    def test_non_digit_story_number_rejected(self):
        # Locks in the `\d+` precision — `story-abc` is not a story
        # branch even with the correct user-prefix shape.
        self.assertIsNone(identity.extract_story_id("paul/story-abc"))

    def test_no_digits_after_story_prefix_rejected(self):
        self.assertIsNone(identity.extract_story_id("paul/story-"))


class TestMergeInProgress(unittest.TestCase):
    """`merge_in_progress` reads MERGE_HEAD, and FAILS CLOSED.

    Its two consumers read the answer in opposite directions — the schedule
    gate exempts a write when it is True, acceptance recovery aborts a merge
    when it is True — so a wrong answer is not symmetrically harmful and there
    is only one honest default: a git failure means "no merge", never "merge".
    Each test builds a fresh repo, because a conflicted merge mutates HEAD.
    """

    def _repo(self) -> str:
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        init_repo_with_ignored_worktrees(td.name)
        return td.name

    def test_true_during_a_conflicted_merge(self):
        repo = self._repo()
        make_conflicted_merge(repo)

        self.assertTrue(identity.merge_in_progress(repo))

    def test_false_on_a_clean_checkout(self):
        """The paired control. Without it, a probe hard-wired to True passes the
        test above and silently exempts every write from the schedule gate."""
        repo = self._repo()
        make_conflicted_merge(repo)
        subprocess.run(
            ["git", "merge", "--abort"], cwd=repo, env=GIT_ENV, capture_output=True
        )

        self.assertFalse(identity.merge_in_progress(repo))

    def test_false_once_the_merge_is_committed(self):
        """Resolving and committing the merge closes the window. This is the
        transition the schedule gate rides: exempt while conflicted, gated again
        the moment the merge lands."""
        repo = self._repo()
        make_conflicted_merge(repo)
        (Path(repo) / "base.txt").write_text("resolved\n")
        for args in (["add", "base.txt"], ["commit", "--no-edit"]):
            subprocess.run(
                ["git", *args], cwd=repo, env=GIT_ENV, capture_output=True, check=True
            )

        self.assertFalse(identity.merge_in_progress(repo))

    def test_false_in_a_repo_with_no_merge_ever_started(self):
        self.assertFalse(identity.merge_in_progress(self._repo()))

    def test_false_when_the_directory_is_not_a_repo(self):
        """Fail CLOSED. `git rev-parse` exits non-zero outside a repo, and the
        answer must be "no merge" — an exemption is a claim, and a claim we
        cannot substantiate is not one we make."""
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(identity.merge_in_progress(td))

    def test_false_when_the_path_does_not_exist(self):
        self.assertFalse(identity.merge_in_progress("/nonexistent/path"))

    def test_a_bare_repo_with_no_head_is_not_a_merge(self):
        """A repo with no commits at all: HEAD is unborn, so nearly every
        rev-parse fails. Still not a merge."""
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(
                ["git", "init", "-b", "main"], cwd=td, capture_output=True, check=True
            )
            self.assertFalse(identity.merge_in_progress(td))


class TestUnmergedPaths(unittest.TestCase):
    """`unmerged_paths` names the files a conflict is actually being resolved in.

    The schedule gate exempts a write while a conflict is being resolved, and
    MERGE_HEAD alone cannot say WHICH file that is: it exempts every write for
    as long as the merge exists, and an abandoned merge (neither committed nor
    aborted — `acceptance_env.detect_interrupted` treats exactly that leftover
    as a crashed run, so it persists) then disarmed the gate wholesale. The
    index's unmerged entries are the narrower fact, and they self-clear per
    file as each is resolved and staged.

    Fails CLOSED like its neighbours: no repo, no git, no answer means no
    exemption, so every failure returns an EMPTY set.
    """

    def _repo(self) -> str:
        td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(td.cleanup)
        init_repo_with_ignored_worktrees(td.name)
        return td.name

    def _git(self, repo: str, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=repo, env=GIT_ENV, capture_output=True, check=True
        )

    def test_the_conflicted_file_is_named(self):
        repo = self._repo()
        make_conflicted_merge(repo)

        self.assertEqual(identity.unmerged_paths(repo), {"base.txt"})

    def test_a_resolved_and_staged_file_leaves_the_set(self):
        """The self-clearing half, and the reason this is narrower than
        MERGE_HEAD: staging the resolution ends that file's exemption even
        though the merge itself is still in progress."""
        repo = self._repo()
        make_conflicted_merge(repo)
        (Path(repo) / "base.txt").write_text("resolved\n")
        self._git(repo, "add", "base.txt")

        self.assertTrue(identity.merge_in_progress(repo), "still mid-merge")
        self.assertEqual(identity.unmerged_paths(repo), set())

    def test_a_clean_checkout_has_none(self):
        self.assertEqual(identity.unmerged_paths(self._repo()), set())

    def test_a_non_repo_has_none(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(identity.unmerged_paths(td), set())

    def test_paths_are_repo_relative_from_a_subdirectory(self):
        """`git ls-files` reports paths relative to the CWD by default, so a
        hook firing from a subdirectory would otherwise get `../base.txt` and
        match nothing. The caller joins these onto the repo root."""
        repo = self._repo()
        make_conflicted_merge(repo)
        sub = Path(repo) / "sub"
        sub.mkdir()

        self.assertEqual(identity.unmerged_paths(str(sub)), {"base.txt"})


class TestExactlyOneMergeDetector(unittest.TestCase):
    """`acceptance_env` must not keep a second MERGE_HEAD probe of its own.

    Two probes is how the schedule gate and acceptance recovery come to
    disagree about whether a merge is in progress. The dependency direction is
    deliberate and one-way: acceptance_env reads identity (it already did, for
    `get_current_branch`), while `pre_tool_write` must NOT reach the other way —
    acceptance_env is serial acceptance mechanics and the Write hook is a hot
    path.
    """

    def test_acceptance_env_reads_the_shared_probe(self):
        import acceptance_env

        with tempfile.TemporaryDirectory() as td:
            init_repo(td)
            with patch.object(
                identity, "merge_in_progress", return_value=True
            ) as probe:
                state = acceptance_env.detect_interrupted(td)

        self.assertEqual(state, "in-progress-merge")
        probe.assert_called_once_with(td)


if __name__ == "__main__":
    unittest.main()
