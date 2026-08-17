#!/usr/bin/env python3
"""Tests for git_write_exit_gate.py — refuse a push/commit whose status is lost.

On 2026-08-14 a `git push` was piped through `tail -6`. The shell reported
`tail`'s exit 0, the push had been rejected, and ~40 minutes went into chasing a
bug that did not exist. The sibling gate did not fire because it keys on the
project's DECLARED TEST COMMAND, and a push is not it — the push shape had zero
coverage, not partial coverage.

THE VACUITY TRAP THIS SUITE IS BUILT AGAINST. `outer_exit_reaches_shell` returns
True when the target is never seen — a command that runs nothing has no
swallowed status — so every "allowed" assertion here passes trivially against a
predicate matching NOTHING AT ALL. A suite of only-allowed tests would be green
against a gate that is entirely inert. The refused table is therefore the
load-bearing half, and `TestThePredicateIsNotVacuous` pins the two mutations
that would hollow it out.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import git_write_exit_gate
import shell_exit_structure
from _bases import _AssertNotNoneMixin

# Every shape that loses the status. The first is the recorded defect verbatim.
_MASKING_SHAPES = {
    "the-recorded-defect": "git push origin HEAD 2>&1 | tail -6",
    "commit-piped": "git commit -m x | tail -20",
    "wrapper-laundered": "sh -c 'git push' | tee push.log",
    "semicolon": "git push; echo done",
    "or-mask": "git push || true",
    "assignment-capture": "OUT=$(git push)",
    "consumed-capture": "echo $(git push)",
    "backtick-capture": "echo `git push`",
    "background": "git push &",
    "redirect-then-echo": "git push > push.log\necho $?",
    # `git -C <path>` is the form agents adopt to avoid cd-poisoning the Stop
    # hooks, and it is what the shipped close skills instruct. Without
    # `GIT_PREFIX` a bare `git\\s+` would walk straight past every one of them.
    "dash-C-push": "git -C /tmp/wt push | tail -6",
    "dash-C-commit": "git -C /tmp/wt commit -m x | tail -6",
}

# Shapes that keep git's exit status, and must not be refused.
_HONEST_SHAPES = {
    "bare-push": "git push",
    "bare-commit": 'git commit -m "fix"',
    "leading-cd": "cd repo && git push",
    "trailing-and": "git push && echo pushed",
    "both": "cd repo && git add -A && git commit -m x && git push",
    "dash-C-chain": "git -C /tmp/wt add -A && git -C /tmp/wt commit -m x",
    # A redirect alone moves the OUTPUT, not the status — which is exactly what
    # the refusal below offers as the answer, so it has to actually be allowed.
    "redirect-only": "git push > push.log",
    "redirect-both-streams": "git push > push.log 2>&1",
    # Reads, not writes. The gate must not spread to the whole git vocabulary:
    # a piped `git log` loses nothing anyone needed.
    "piped-log": "git log --oneline | tail -6",
    "piped-status": "git status --short | head -20",
    "piped-diff": "git diff --stat | tail -3",
    # `git commit-tree` is a plumbing read-write that is not this gate's shape,
    # and the `(?!-)` guard is what keeps it out — the same guard the sibling
    # `_COMMIT_OR_MERGE_RE` uses ten lines away in `git_commits`.
    "commit-tree": "git commit-tree $TREE -p HEAD -m x | cat",
}


class TestAPushOrCommitThatLosesItsStatusIsRefused(unittest.TestCase):
    """Why these two subcommands and no others: `pre-push` runs the entire
    suite and `pre-commit` runs lint, format, types and the staged tests. Those
    hooks exist to FAIL, and a pipe throws away the one signal they produce —
    while the output being long is precisely why the pipe gets typed."""

    def test_every_masking_shape_is_refused(self):
        for name, command in _MASKING_SHAPES.items():
            with self.subTest(shape=name):
                self.assertIsNotNone(
                    git_write_exit_gate.captured_git_write_block(command),
                    msg=f"{command!r} loses git's exit status and was allowed",
                )

    def test_every_honest_shape_is_allowed(self):
        for name, command in _HONEST_SHAPES.items():
            with self.subTest(shape=name):
                self.assertIsNone(
                    git_write_exit_gate.captured_git_write_block(command),
                    msg=f"{command!r} keeps git's exit status and was refused",
                )

    def test_an_empty_command_is_allowed(self):
        self.assertIsNone(git_write_exit_gate.captured_git_write_block(""))


class TestTheFalsePositivesThatWouldRefuseOurOwnCommits(unittest.TestCase):
    """Named regression pins, not incidental cases.

    EVERY commit on this branch uses the heredoc form, and several of their
    messages contain the literal text `git add -A && git commit`. If either of
    these were mishandled the gate would refuse the very commits that ship it —
    which is a thing to prove once, in a test that says why, rather than to
    rediscover at the next commit.
    """

    def test_a_heredoc_body_is_not_read_as_shell(self):
        """`strip_quoted` calls `strip_heredocs` before segmentation, so a
        body's newlines are not segment breaks. Without that, a multi-line
        commit message reads as `git commit` followed by a `\\n` that discards
        its status, and no commit could ever be made with a message."""
        command = (
            "git add -A && git commit -F - <<'EOF'\n"
            "Title line\n"
            "\n"
            "A body paragraph that runs over several lines and mentions a\n"
            "pipe | and a semicolon ; in passing.\n"
            "EOF"
        )
        self.assertIsNone(git_write_exit_gate.captured_git_write_block(command))

    def test_a_commit_message_quoting_a_piped_push_is_not_refused(self):
        """The message TALKS ABOUT the refused shape. Quoted text is not code,
        and a gate that cannot tell the difference cannot be used to describe
        its own bug in the commit that fixes it."""
        command = (
            "git commit -F - <<'EOF'\n"
            "Refuse a push whose status is lost\n"
            "\n"
            "`git push | tail -6` reported tail's exit 0 while the push failed.\n"
            "EOF"
        )
        self.assertIsNone(git_write_exit_gate.captured_git_write_block(command))

    def test_an_argument_substitution_is_not_a_capture(self):
        """`git commit -m "$(cat msg.txt)"` is ONE command whose exit status is
        git's; the substitution computes an argument. Refusing these is the
        direction that silently disabled a different consumer for a whole class
        of projects once already."""
        self.assertIsNone(
            git_write_exit_gate.captured_git_write_block(
                'git commit -m "$(cat msg.txt)"'
            )
        )


class TestTheEscapeHatch(unittest.TestCase):
    def test_the_marker_suppresses_the_refusal(self):
        marker = shell_exit_structure.EXIT_STATUS_NOT_NEEDED_MARKER
        self.assertIsNone(
            git_write_exit_gate.captured_git_write_block(
                f"git push | tail -6  {marker}"
            )
        )

    def test_the_same_command_without_it_is_refused(self):
        """The control. Without this the test above passes against a gate that
        refuses nothing."""
        self.assertIsNotNone(
            git_write_exit_gate.captured_git_write_block("git push | tail -6")
        )

    def test_the_marker_is_a_shell_comment_so_it_cannot_change_what_runs(self):
        self.assertTrue(
            shell_exit_structure.EXIT_STATUS_NOT_NEEDED_MARKER.startswith("#")
        )

    def test_both_gates_are_waived_by_one_marker(self):
        """One shape refused, one thing to remember. An agent made to recall
        which marker suppresses which gate will type the wrong one."""
        import exit_capture_gate

        self.assertEqual(
            exit_capture_gate.EXIT_STATUS_NOT_NEEDED_MARKER,
            shell_exit_structure.EXIT_STATUS_NOT_NEEDED_MARKER,
        )


class TestTheRefusalSaysWhatToTypeNext(_AssertNotNoneMixin, unittest.TestCase):
    """A refusal that does not name the fix costs the run it just saved."""

    def setUp(self):
        self.push = self._assert_not_none(
            git_write_exit_gate.captured_git_write_block(
                "git push origin HEAD 2>&1 | tail -6"
            )
        )
        self.commit = self._assert_not_none(
            git_write_exit_gate.captured_git_write_block("git commit -m x | tail -20")
        )

    def test_it_names_the_offending_subcommand(self):
        self.assertIn("push", self.push)
        self.assertIn("commit", self.commit)

    def test_it_says_the_and_chain_is_still_fine(self):
        """Without this the obvious reading is 'never compose a push', and the
        next attempt drops the `cd <dir> &&` a worktree run needs."""
        self.assertIn("&&", self.push)

    def test_it_offers_the_redirect(self):
        """The output being long is WHY the pipe was typed. 'Re-run it bare'
        throws that output away; a redirect keeps it and keeps the status."""
        self.assertIn("2>&1", self.push)

    def test_it_names_the_escape_marker(self):
        self.assertIn(shell_exit_structure.EXIT_STATUS_NOT_NEEDED_MARKER, self.push)


class TestThePredicateIsNotVacuous(unittest.TestCase):
    """The two mutations that would hollow out the refused table above.

    Neither is hypothetical: a predicate matching nothing passes every allowed
    assertion in this file, and a bare `git\\s+` is the spelling anyone would
    reach for before noticing `git -C <path>`.
    """

    def test_the_predicate_matches_the_shapes_the_refusals_depend_on(self):
        for command in _MASKING_SHAPES.values():
            with self.subTest(command=command):
                self.assertIsNotNone(
                    git_write_exit_gate.git_write_named(command),
                    msg="a predicate blind here would make the refusal vacuous",
                )

    def test_the_predicate_declines_a_read(self):
        """The other direction: a predicate matching EVERYTHING also passes the
        refused table, and would refuse `git log | tail` with it."""
        for name in ("piped-log", "piped-status", "piped-diff", "commit-tree"):
            with self.subTest(shape=name):
                self.assertIsNone(
                    git_write_exit_gate.git_write_named(_HONEST_SHAPES[name])
                )

    def test_the_dash_c_form_is_what_git_prefix_buys(self):
        """Mutation pin: drop `GIT_PREFIX` for a bare `git\\s+` and this is the
        assertion that reddens."""
        self.assertEqual(
            git_write_exit_gate.git_write_named("git -C /tmp/wt push"), "push"
        )

    def test_a_quoted_git_write_still_names_its_subcommand(self):
        """`strip_quoted` removes the quoted token, so `git "x" push` reads as a
        write only AFTER stripping — while `sh -c 'git push'` reads as one only
        BEFORE it. The walk sees both, so the pre-filter has to as well."""
        self.assertEqual(git_write_exit_gate.git_write_named('git "x" push'), "push")
        self.assertEqual(
            git_write_exit_gate.git_write_named("sh -c 'git push'"), "push"
        )


if __name__ == "__main__":
    unittest.main()
