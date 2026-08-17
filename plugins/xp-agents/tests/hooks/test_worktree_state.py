#!/usr/bin/env python3
"""The working-tree question: what is uncommitted in this checkout.

Split from `test_commits_issues.py` alongside the module it tests. The
subprocess patch target stays `commits.subprocess.run` — `worktree_state`
leans on `commits._run_git` rather than shelling out itself, so patching the
module that owns the call is what actually intercepts it. Patching
`worktree_state.subprocess` would bind nothing and every test here would pass
against the real git.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import worktree_state

_SUBPROCESS = "commits.subprocess.run"


class TestGetUncommittedCodeFiles(unittest.TestCase):
    """Tests for worktree_state.get_uncommitted_code_files()."""

    @patch(_SUBPROCESS)
    def test_returns_code_files_only(self, mock_run):
        """Filters out non-code files and test files."""
        staged = type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": ("src/app.py\0README.md\0tests/test_app.py\0"),
            },
        )()
        unstaged = type("R", (), {"returncode": 0, "stdout": "src/utils.py\n"})()
        mock_run.side_effect = [staged, unstaged]
        result = worktree_state.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, ["src/app.py", "src/utils.py"])

    @patch(_SUBPROCESS)
    def test_empty_on_no_changes(self, mock_run):
        """No changed files -> empty list."""
        empty = type("R", (), {"returncode": 0, "stdout": ""})()
        mock_run.side_effect = [empty, empty]
        result = worktree_state.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, [])

    @patch(_SUBPROCESS)
    def test_deduplicates_staged_and_unstaged(self, mock_run):
        """Same file in both staged and unstaged -> appears once."""
        staged = type("R", (), {"returncode": 0, "stdout": "src/app.py\n"})()
        unstaged = type("R", (), {"returncode": 0, "stdout": "src/app.py\n"})()
        mock_run.side_effect = [staged, unstaged]
        result = worktree_state.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, ["src/app.py"])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_empty(self, _mock):
        """Subprocess failure -> empty list (graceful degradation)."""
        result = worktree_state.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# get_uncommitted_files -- the "is the tree dirty?" signal
# ---------------------------------------------------------------------------


def _git_out(stdout: str):
    return type("R", (), {"returncode": 0, "stdout": stdout})()


class TestGetUncommittedFiles(unittest.TestCase):
    """worktree_state.get_uncommitted_files() -- wider than get_uncommitted_code_files.

    Backs the TDD gate's prior-session tree check
    (tdd_check.find_last_test_signal). Every narrowing here is a way to DISARM
    that gate, so test files and untracked files must both count as dirty.
    """

    @patch(_SUBPROCESS)
    def test_includes_test_files(self, mock_run):
        """A tree dirty with ONLY a broken test file is still dirty. The
        narrower get_uncommitted_code_files drops it and reads CLEAN."""
        mock_run.side_effect = [
            _git_out(""),
            _git_out("tests/test_app.py\n"),
            _git_out(""),
        ]
        self.assertEqual(
            worktree_state.get_uncommitted_files("/tmp"), ["tests/test_app.py"]
        )

    @patch(_SUBPROCESS)
    def test_includes_untracked_files(self, mock_run):
        """`git diff` never lists untracked files -- but a brand-new, never-added
        failing test is the most common shape of the TDD red step."""
        mock_run.side_effect = [
            _git_out(""),
            _git_out(""),
            _git_out("tests/test_new.py\0src/new_mod.py\0"),
        ]
        self.assertEqual(
            worktree_state.get_uncommitted_files("/tmp"),
            ["src/new_mod.py", "tests/test_new.py"],
        )

    @patch(_SUBPROCESS)
    def test_excludes_non_code_and_dedups(self, mock_run):
        """Docs churn is not broken work; a file in two lists appears once."""
        mock_run.side_effect = [
            _git_out("src/app.py\0README.md\0"),
            _git_out("src/app.py\n"),
            _git_out(""),
        ]
        self.assertEqual(worktree_state.get_uncommitted_files("/tmp"), ["src/app.py"])

    @patch(_SUBPROCESS)
    def test_empty_on_clean_tree(self, mock_run):
        mock_run.side_effect = [_git_out(""), _git_out(""), _git_out("")]
        self.assertEqual(worktree_state.get_uncommitted_files("/tmp"), [])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_no_repo_reads_clean(self, _mock):
        """Graceful degradation. git is absent / this is not a work tree: a
        structural, permanent condition. Reads as CLEAN, so a project git
        cannot answer for at all never gates forever on a prior-session
        failure."""
        self.assertEqual(worktree_state.get_uncommitted_files("/tmp"), [])

    @patch(_SUBPROCESS)
    def test_scan_timeout_in_a_real_repo_is_unanswered_not_clean(self, mock_run):
        """Anti-disarm, and the reason "no answer" is not one condition.

        The untracked scan walks the WHOLE worktree, so it is the likeliest
        _run_git timeout here. Collapsing that to "no files" reads as a CLEAN
        tree and UN-GATES a real prior-session failure. The O(1) repo probe
        still answers when the walking scan does not, which is what tells this
        apart from the no-repo case above.
        """
        mock_run.side_effect = [
            _git_out(""),  # staged
            _git_out(""),  # unstaged
            subprocess.TimeoutExpired(cmd="git ls-files", timeout=5),
            _git_out("true"),  # repo probe: yes, this really is a work tree
        ]
        self.assertIsNone(worktree_state.get_uncommitted_files("/tmp"))


class TestThePatchTargetCannotDriftSilently(unittest.TestCase):
    """The one way every test above could pass while proving nothing.

    They patch `commits.subprocess.run`, because `worktree_state` shells out
    through `commits._run_git` rather than calling subprocess itself. A reader
    who "corrects" the target to `worktree_state.subprocess` would be aiming at
    a name this module does not have — and the failure mode matters: if the
    module ever grows its own `subprocess` import, that mis-aimed patch starts
    binding a real object that nothing calls, and all ten tests above go green
    against real git in whatever repo they happen to run in.

    So the invariant is not "the target string is spelled thus" but "there is
    no second plausible target here to aim at". `mock.patch` raises
    AttributeError on a missing attribute, which is loud; a present-but-unused
    one is what would be silent.
    """

    def test_the_module_owns_no_subprocess_of_its_own(self):
        self.assertFalse(
            hasattr(worktree_state, "subprocess"),
            "worktree_state must not import subprocess: it delegates to "
            "commits._run_git, and a second plausible patch target here is "
            "what would let a mis-aimed patch pass against real git",
        )

    def test_the_declared_target_actually_intercepts_this_module(self):
        """Non-vacuity for the target these tests do use."""
        with patch(_SUBPROCESS) as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0, "stdout": ""})()
            worktree_state.get_uncommitted_code_files("/tmp")
        self.assertTrue(
            mock_run.called,
            f"{_SUBPROCESS} did not intercept a worktree_state call — the "
            "patch target no longer reaches the code under test",
        )


if __name__ == "__main__":
    unittest.main()
