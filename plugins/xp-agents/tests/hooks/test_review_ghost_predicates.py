#!/usr/bin/env python3
"""Which commands stage, name, or absorb a path — the ghost filter's predicates.

Split from `test_review_ghosts.py` when the pathspec leg took that file over the
500-line cap. The seam is what the rows need to run: the classes left there
drive a REAL repo, because the ghost rule is a claim about what git reports;
these read a command STRING and answer about it, which is the other half of the
same rule and the half a hand-rolled regex kept getting wrong.

`git_commits.py` records what each spelling cost. The short version: `commit -q
-a`, `commit --all`, `git commit <pathspec>` and a `git add` inside a commit
MESSAGE have each slipped one of these predicates, and each miss was silent —
the gate counted fewer code files and let the commit through.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import git_commits


class TestWhichCommandsNameAPathspec(unittest.TestCase):
    """`commit_names_a_pathspec`, and which way each judgement leans.

    Same lean as `stages_all_tracked_changes` above and for the same reason: a
    false YES stands the ghost filter down and costs one extra review, a false
    NO is the silent under-block. So an argument this cannot place reads as a
    pathspec.
    """

    def test_the_forms_that_name_paths(self):
        for command in (
            "git commit a.py",
            "git commit -m wip a.py",
            "git commit -m 'wip' src/a.py src/b.py",
            "git commit --amend -m 'wip' a.py",
            "git commit -- a.py",
            "git -C /some/worktree commit -m 'wip' a.py",
            "git commit \\\n  -m 'wip' a.py",
            # `--message=` carries its own value, so the next token is a path.
            "git commit --message='wip' a.py",
        ):
            with self.subTest(command=command):
                self.assertTrue(git_commits.commit_names_a_pathspec(command))

    def test_the_forms_that_commit_the_index(self):
        for command in (
            "git commit",
            "git commit -m 'wip'",
            # Unquoted single-word message: `-m` takes its value as a separate
            # token, so this is the message and not a path.
            "git commit -m wip",
            "git commit --amend --no-edit",
            "git commit -F .git/MSG",
            "git commit --author='a <a@b.c>' -m 'wip'",
            "git status && git add notes.md",
            # A pathspec in a LATER command says nothing about this one, and a
            # message body mentioning a path is not one.
            "git commit -m 'wip'; ls a.py",
            "git commit -m 'touched a.py'",
        ):
            with self.subTest(command=command):
                self.assertFalse(git_commits.commit_names_a_pathspec(command))


class TestWhichCommandsStageEverything(unittest.TestCase):
    """`stages_all_tracked_changes`, the predicate the rule keys on.

    A false YES over-counts, which costs one extra review; a false NO is the
    silent under-block above. So the forms are enumerated generously, and the
    pins below say which way each judgement leans.
    """

    def test_the_forms_that_stage_every_tracked_deletion(self):
        for command in (
            "git add -A",
            "git add --all",
            "git add -A .",
            "git add -u",
            "git add --update",
            "git add .",
            "git commit -a",
            "git commit -am wip",
            "git commit -q -a -m wip",
            "git commit --all -m wip",
            "git -C /some/worktree add -A",
            "git add \\\n  -A",
            # Clustered short options. `-A` and `-v` are both bool flags, so
            # git accepts either order in one token; matching `-A` alone made
            # both a silent NO, which is the under-block direction.
            "git add -Av",
            "git add -vA",
            "git commit -aq -m wip",
        ):
            with self.subTest(command=command):
                self.assertTrue(git_commits.stages_all_tracked_changes(command))

    def test_the_forms_that_do_not(self):
        for command in (
            "git add notes.md",
            "git add src/",
            "git add ./src",
            "git commit -m notes",
            "git commit --amend --no-edit",
            "git commit -m 'add -A everywhere'",
            "git status",
            "git add -p",
            "git add -n",
            "git add -N src/x.py",
            "git commit --author=alice -m wip",
            "git commit --fixup=abc",
            "git commit --untracked-files=all -m wip",
        ):
            with self.subTest(command=command):
                self.assertFalse(git_commits.stages_all_tracked_changes(command))

    def test_a_shared_scan_target_is_actually_consulted(self):
        """The kwarg exists so a caller can share one `strip_quoted` pass with
        `is_git_commit`, the way `bash_post_tool` already does for that
        predicate. Untested it was a branch free to ignore what it was handed,
        which is what `a7cb61e6d206` recorded: the two arguments here disagree,
        so only reading `scan_target` can give the second answer.
        """
        raw = "git commit -m notes"

        self.assertFalse(git_commits.stages_all_tracked_changes(raw))
        self.assertTrue(
            git_commits.stages_all_tracked_changes(
                raw, scan_target="git add -A && git commit -m notes"
            )
        )

    def test_it_cannot_reach_across_a_shell_operator(self):
        """A stage-all in a LATER command says nothing about this one, and the
        reverse would let any trailing `git add -A` disarm the filter for a
        commit that stages one path."""
        self.assertFalse(
            git_commits.stages_all_tracked_changes("git add notes.md && echo -A")
        )
        self.assertFalse(
            git_commits.stages_all_tracked_changes("git commit -m x; ls -a")
        )

    def test_a_bare_newline_ends_a_command_like_a_semicolon(self):
        """The operator class has to include the newline, or a multi-line
        script reads as a stage-all because its LAST line carries an `-a`. That
        stands the ghost filter down and hands back the over-block the filter
        exists to prevent (concern 64c18a0a3a48). A `\\`-newline is the one
        crossable form — the shell joins it away before git parses anything,
        and the wrapped `git add \\<newline> -A` above stays a YES.
        """
        for command in (
            "git add notes.md\ngit commit -m notes\nls -la",
            "git commit -m x\nls -a",
            "git add notes.md\nls .",
        ):
            with self.subTest(command=command):
                self.assertFalse(git_commits.stages_all_tracked_changes(command))


class TestWhichCommandsStageAPath(unittest.TestCase):
    """`stages_a_path`, the third predicate the scan asks — and the one that
    was still reading the RAW command.

    It answers a DIFFERENT question from `stages_all_tracked_changes`: a narrow
    `git add notes.md` widens the scan to the whole unstaged diff (an
    over-count, on purpose — a wider set blocks) but leaves an unstaged deletion
    a ghost. The two must not collapse into one.
    """

    def test_any_add_widens_the_scan(self):
        for command in ("git add notes.md", "git add -A", "git -C /wt add src/"):
            with self.subTest(command=command):
                self.assertTrue(git_commits.stages_a_path(command))

    def test_a_message_that_mentions_one_does_not(self):
        """The raw scan matched the `git add` inside a commit MESSAGE and
        widened the review scan for prose — the same class of bug every other
        predicate here is quote-stripped to avoid."""
        self.assertFalse(git_commits.stages_a_path('git commit -m "git add -A"'))
        self.assertFalse(git_commits.stages_a_path("git commit -m 'run git add'"))

    def test_a_narrow_add_is_not_a_stage_all(self):
        self.assertTrue(git_commits.stages_a_path("git add notes.md"))
        self.assertFalse(git_commits.stages_all_tracked_changes("git add notes.md"))


if __name__ == "__main__":
    unittest.main()
