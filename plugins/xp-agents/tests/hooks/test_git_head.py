#!/usr/bin/env python3
"""Reading HEAD from git's own files, across the layouts that actually occur.

`commit_observer` asks what HEAD is on EVERY Bash, and almost every answer is
"unchanged". A `git rev-parse` fork to learn that would put the cost of
watching on the path where nothing happened, so the observer reads the files
instead — and then has to be right about the layouts a fork would have handled
for free.

Each case below is one of those layouts, driven against a REAL repo git itself
produced: a stub could assert any file arrangement into existence, including
ones git never writes.

The failure mode this guards is specific and nasty: every wrong answer here is
`None`, which the observer treats as "cannot say" and skips. So a reader that
mishandles packed refs does not crash — it silently stops recording commits on
any repo that has been `git gc`'d, which is exactly the class of silent gap the
whole story exists to close.
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import git_head


class _RepoCase(unittest.TestCase):
    """A real repo with one commit, plus whatever each test does to it."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main", ".")
        self.git("config", "user.email", "t@t.com")
        self.git("config", "user.name", "T")
        (self.repo / "README.md").write_text("init")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(f"git {args!r} failed: {result.stderr}")
        return result.stdout.strip()

    def head(self, cwd: Path | None = None) -> str:
        return self.git("rev-parse", "HEAD", cwd=cwd)


class TestOrdinaryClone(_RepoCase):
    def test_it_agrees_with_rev_parse(self):
        self.assertEqual(git_head.read_head(str(self.repo)), self.head())

    def test_a_subdirectory_walks_up_to_the_checkout(self):
        """cwd is routinely a subdirectory, and `.git` is only at the root."""
        nested = self.repo / "a" / "b"
        nested.mkdir(parents=True)
        self.assertEqual(git_head.read_head(str(nested)), self.head())

    def test_a_detached_head_reads_the_object_name_directly(self):
        """No `ref:` line to follow — HEAD holds the hash itself."""
        expected = self.head()
        self.git("checkout", "-q", "--detach")
        self.assertEqual(git_head.read_head(str(self.repo)), expected)

    def test_a_packed_ref_still_resolves(self):
        """`git gc` deletes the loose ref file. A reader that only stats
        `refs/heads/<branch>` reports None from here on — silently, and only on
        repos that have been packed."""
        expected = self.head()
        self.git("pack-refs", "--all")
        self.assertFalse((self.repo / ".git" / "refs" / "heads" / "main").exists())
        self.assertEqual(git_head.read_head(str(self.repo)), expected)

    def test_a_loose_ref_wins_over_a_stale_packed_one(self):
        """`git pack-refs` writes the pack BEFORE deleting the loose file, so
        the two coexist and disagree during that window. Loose is newer."""
        self.git("pack-refs", "--all")
        (self.repo / "next.txt").write_text("next")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "after packing")
        self.assertEqual(git_head.read_head(str(self.repo)), self.head())


class TestLinkedWorktree(_RepoCase):
    """How every teammate in this project runs: `.git` is a FILE, HEAD is
    per-worktree, and `refs/heads/*` lives in the shared common dir."""

    def setUp(self):
        super().setUp()
        self.wt = Path(tempfile.mkdtemp()) / "worktree-story-999"
        self.git("worktree", "add", "-q", "-b", "side", str(self.wt))

    def tearDown(self):
        shutil.rmtree(self.wt.parent, ignore_errors=True)
        super().tearDown()

    def test_the_worktree_head_is_read_not_the_main_checkout_one(self):
        (self.wt / "side.txt").write_text("side")
        self.git("add", "-A", cwd=self.wt)
        self.git("commit", "-q", "-m", "side work", cwd=self.wt)
        self.assertEqual(git_head.read_head(str(self.wt)), self.head(cwd=self.wt))
        self.assertNotEqual(git_head.read_head(str(self.wt)), self.head())

    def test_the_dot_git_file_is_followed_not_treated_as_a_directory(self):
        self.assertTrue((self.wt / ".git").is_file())
        self.assertEqual(git_head.read_head(str(self.wt)), self.head(cwd=self.wt))

    def test_a_packed_ref_resolves_through_the_common_dir(self):
        """The pack lives in the MAIN repo's dir, not the worktree's gitdir."""
        expected = self.head(cwd=self.wt)
        self.git("pack-refs", "--all")
        self.assertEqual(git_head.read_head(str(self.wt)), expected)


class TestCannotSay(_RepoCase):
    """Every unanswerable case returns None, never a guess."""

    def test_a_directory_that_is_not_a_repo(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside, True)
        self.assertIsNone(git_head.read_head(str(outside)))

    def test_a_fresh_repo_with_no_commit_yet(self):
        """HEAD names a branch that does not exist. Not an error — there is
        genuinely no commit — but it is not an object name either."""
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, True)
        subprocess.run(
            ["git", "init", "-q", "-b", "main", "."],
            cwd=empty,
            capture_output=True,
            check=True,
        )
        self.assertIsNone(git_head.read_head(str(empty)))

    def test_a_head_file_holding_something_that_is_not_an_object_name(self):
        (self.repo / ".git" / "HEAD").write_text("not a hash\n")
        self.assertIsNone(git_head.read_head(str(self.repo)))

    def test_a_dot_git_file_pointing_nowhere(self):
        broken = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, broken, True)
        (broken / ".git").write_text("gitdir: /nonexistent/elsewhere\n")
        self.assertIsNone(git_head.read_head(str(broken)))


if __name__ == "__main__":
    unittest.main()
