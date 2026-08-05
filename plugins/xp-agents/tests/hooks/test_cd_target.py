#!/usr/bin/env python3
"""The `cd` target parse, and the refusal for a `cd` path we cannot recover.

A new file rather than more of test_commit_command.py, which sits at 445 lines
against a 450 band floor and a 500 cap — these tests would breach the cap. The
split mirrors the one already made for the `-C` side
(test_pre_tool_bash_git_c_target.py): this is the `cd` half of the same question,
"which repo does the commit actually land in".

story-011 fixed `-C` by locating the flag on an offset-preserving MASK and
reading the path from the RAW command at the same offsets. `cd` was left on the
quote-STRIPPED text, where `strip_quoted` DELETES the span — so
`cd "/a real dir" && git commit` becomes `cd  && git commit`, the path token
cannot match `&&`, and `parse_effective_cwd` silently returns the caller's cwd.
Every gate below then reads the wrong repo, and an empty `git diff --cached` is
not None, so the fail-closed never fires: the commit ships unscanned, unlinted
and unreviewed. A worktree path containing a space MUST be quoted, so this is
ordinary usage rather than obfuscation.

The load-bearing constraint in the other direction: the `cd` pass was put on the
stripped text to make a commit MESSAGE that mentions `cd /tmp` invisible. Masking
preserves that (it fills quoted contents and heredoc bodies while keeping the
delimiters), so both properties hold at once — but only the tests below say so.
The immunity pins live in test_pre_tool_bash.py and stay green UNEDITED; the ones
here are the reachability half.

Both LEVELS live here — the unit predicates and the gate-level refusal — grouped
by SUBJECT rather than by level. The gate classes started out in
test_pre_tool_bash_git_c_target.py and pushed it to 485 lines, past the 450 band
floor; moving them returned that file to its pre-story size and put every `cd`
assertion in one place, which is what a reader looking for "what does the gate do
with a cd?" actually wants.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from unittest.mock import patch

import _common
import commit_command
import pre_tool_bash
from conftest import _HookTestCase, _make_bash_input


class _CdTargetTestCase(unittest.TestCase):
    """Builds the fixture the defect needs: a real directory whose name has a
    SPACE, so the quoting is load-bearing rather than incidental.

    THE FALLBACK IS A THIRD DIRECTORY, distinct from every expected answer. Using
    one directory as both the fallback and the target makes "resolved the path
    correctly" indistinguishable from "silently fell back" — the failure mode
    under test is *exactly* a silent fallback, so a shared fixture would let
    every assertion below pass against the broken code. Two of these tests did
    pass that way before the fallback was split out.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = self._tmp.name
        self.fallback = os.path.join(root, "caller-repo")
        self.plain = os.path.join(root, "plain")
        self.spacey = os.path.join(root, "a real dir")
        for path in (self.fallback, self.plain, self.spacey):
            os.mkdir(path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _parse(self, command: str) -> str:
        return commit_command.parse_effective_cwd(command, self.fallback)


class TestQuotedCdPathResolves(_CdTargetTestCase):
    """The reachability half. Each of these returns the FALLBACK today."""

    def test_double_quoted_cd_path_resolves(self):
        self.assertEqual(
            self._parse(f'cd "{self.spacey}" && git commit -m x'), self.spacey
        )

    def test_single_quoted_cd_path_resolves(self):
        self.assertEqual(
            self._parse(f"cd '{self.spacey}' && git commit -m x"), self.spacey
        )

    def test_an_escaped_quote_in_the_message_keeps_the_bare_cd(self):
        """A CONTROL, not a fix — and it is here because I briefly recorded it as
        a fix. An earlier measurement said this form loses even its bare outer
        `cd`; that reading came from a probe using the same directory as both the
        fallback and the expected answer, which cannot tell "fell back" from
        "resolved correctly". Re-measured against a distinct fallback, it resolves
        correctly today. It stays as a guard: escaped quotes inside the message
        must not disturb the outer `cd` under the mask either."""
        command = f'cd {self.plain} && git commit -m "cd \\"{self.spacey}\\" && x"'
        self.assertEqual(self._parse(command), self.plain)

    def test_bare_unspaced_cd_path_still_resolves(self):
        """Control: the form that works today must keep working. Deliberately
        the UNSPACED path — `cd /a/a real dir` unquoted is invalid in the shell
        too (three words to `cd`), so asserting it resolved would be asserting
        behaviour that should not exist."""
        self.assertEqual(self._parse(f"cd {self.plain} && git commit -m x"), self.plain)


class TestCdPrecedenceIsUnchanged(_CdTargetTestCase):
    """The rules the swap must NOT disturb. These pass before and after — they
    are here because the pass they guard is being rewritten underneath them."""

    def test_last_validated_cd_wins_so_cd_back_lands_on_the_first(self):
        """`cd /A && git commit && cd -`: the `-` token is not a directory, so
        it is skipped and /A stands. Last-VALIDATED, not last-matched."""
        command = f"cd {self.plain} && git commit -m x && cd -"
        self.assertEqual(self._parse(command), self.plain)

    def test_dash_c_still_beats_cd(self):
        command = f'cd "{self.spacey}" && git -C "{self.plain}" commit -m x'
        self.assertEqual(self._parse(command), self.plain)

    def test_a_nonexistent_literal_cd_falls_back(self):
        """A literal path that simply does not exist is NOT a hidden target:
        the shell's `cd` fails, `&&` short-circuits, and no commit is made
        anywhere. Falling back is correct and must not become a refusal."""
        command = f"cd {self.plain}/no-such-dir && git commit -m x"
        self.assertEqual(self._parse(command), self.fallback)

    def test_a_message_mentioning_cd_does_not_retarget(self):
        """The immunity, asserted here too rather than only in the pinned file.
        The masked reader is what makes this survive, and a test that only
        proved recovery would let the immunity regress silently. Non-vacuous
        because the answer is `plain` while the fallback is a third directory."""
        command = f'cd {self.plain} && git commit -m "cd {self.spacey} && rm -rf x"'
        self.assertEqual(self._parse(command), self.plain)


class TestCdTargetUnreachable(_CdTargetTestCase):
    """The refusal predicate. Mirrors `dash_c_unreachable`'s doctrine — judge
    EVERY token, because nothing here can attribute a `cd` to the `commit` word —
    with one narrowing the `-C` side does not need: an unreachable `cd` cannot
    move a commit whose target is already pinned by an ABSOLUTE `-C`.
    """

    def _unreachable(self, command: str) -> bool:
        return commit_command.cd_target_unreachable(command)

    def test_a_bare_variable_is_unreachable(self):
        self.assertTrue(self._unreachable("cd $WT && git commit -m x"))

    def test_a_double_quoted_variable_is_unreachable(self):
        """`$` expands inside double quotes, so the hook sees text git never
        will — the same rule `token_unreachable` already applies to `-C`."""
        self.assertTrue(self._unreachable('cd "$WT" && git commit -m x'))

    def test_command_substitution_is_unreachable(self):
        command = 'cd "$(git rev-parse --show-toplevel)" && git commit -m x'
        self.assertTrue(self._unreachable(command))

    def test_a_concatenated_quoting_form_is_unreachable(self):
        """The capture stops at the first segment, so the path as a whole was
        never read — INCOMPLETE, not merely odd."""
        self.assertTrue(self._unreachable("cd '/tmp/'\"$WT\" && git commit -m x"))

    def test_a_backslash_escape_is_unreachable_when_bare(self):
        """`cd /tmp/a\\ dir` hands git ONE path with a space while the capture
        stops at the backslash — the same unread-remainder case."""
        self.assertTrue(self._unreachable("cd /tmp/a\\ dir && git commit -m x"))

    def test_a_single_quoted_variable_is_NOT_unreachable(self):
        """The shell expands nothing inside single quotes, so `cd` receives the
        literal text, fails, `&&` short-circuits and nothing lands. Refusing
        would cost a commit for a command that cannot commit."""
        self.assertFalse(self._unreachable("cd '$WT' && git commit -m x"))

    def test_a_missing_literal_is_NOT_unreachable(self):
        """The `-C` rule this must not break: a literal path that simply does
        not exist is an ordinary failure, not a hidden destination."""
        self.assertFalse(
            self._unreachable(f"cd {self.plain}/no-such-dir && git commit -m x")
        )

    def test_a_resolvable_literal_is_NOT_unreachable(self):
        self.assertFalse(self._unreachable(f'cd "{self.spacey}" && git commit -m x'))

    def test_no_cd_at_all_is_NOT_unreachable(self):
        self.assertFalse(self._unreachable('git -C "$WT" commit -m x'))

    def test_an_absolute_dash_c_pins_the_target_so_the_cd_does_not_matter(self):
        """The narrowing. `-C` beats `cd` in `parse_effective_cwd`, and an
        ABSOLUTE `-C` is unaffected by whatever directory the shell moved to, so
        the destination is fully known and refusing would be a false positive."""
        self.assertFalse(
            self._unreachable(f"cd $WT && git -C {self.plain} commit -m x")
        )

    def test_an_absolute_dash_c_pins_it_even_when_the_dir_is_missing(self):
        """Keyed on ABSOLUTE-and-READABLE, not on absolute-and-exists. A literal
        `-C` naming a directory that is not there makes git abort, so nothing
        lands anywhere — the same rule `dash_c_unreachable` already applies to a
        missing literal. Requiring existence here would refuse a command that
        cannot commit."""
        self.assertFalse(
            self._unreachable("cd $WT && git -C /nope/nothing commit -m x")
        )

    def test_a_RELATIVE_dash_c_does_not_pin_it(self):
        """The reason the narrowing keys on ABSOLUTE rather than merely
        'resolved'. A relative `-C` resolves against the hook's cwd, not the
        post-`cd` cwd, so it lands on a real directory that is NOT where the
        commit goes. Narrowing on 'a -C resolved' would preserve that fail-open.
        """
        os.mkdir(os.path.join(self.fallback, "sub"))
        self.assertTrue(self._unreachable("cd $WT && git -C sub commit -m x"))

    def test_a_trailing_unreachable_cd_is_still_refused(self):
        """The accepted cost, pinned so it is a decision and not an accident:
        `git commit && cd $HOME` commits before the `cd` runs, yet is refused.
        Nothing here can attribute a `cd` to the `commit` word, and the remedy
        is the same either way — use a literal path."""
        self.assertTrue(self._unreachable("git commit -m x && cd $HOME"))


class TestUnresolvableCdFailsClosed(_HookTestCase):
    """story-013: the `cd` leg reaches the SAME refusal as `-C`.

    `cd $WT && git commit` left the destination unknowable and was not refused at
    all: `parse_effective_cwd` fell back to the caller's cwd, `git diff --cached`
    came back empty rather than None, and the tier-1 scan, lint gate and review
    gate all no-opped on an empty diff. Shipped prose already tells agents never
    to use this form (TEAMMATE_GUIDE, xp-accept, the close pipeline), so the
    refusal enforces our own instructions rather than adding a new rule.
    """

    def _run(self, command: str, cwd: str = "/tmp"):
        return pre_tool_bash.run(
            _make_bash_input(command=command, cwd=cwd), smm_dir=self.smm_dir
        )

    def _assert_blocked(self, command: str) -> str:
        with self.assertRaises(_common.BlockedError) as ctx:
            self._run(command)
        return str(ctx.exception)

    @patch("git_commits.is_git_commit", return_value=True)
    def test_variable_cd_is_blocked_and_the_reason_names_cd(self, *_mocks):
        """The reason must name `cd`. A message that only talks about `git -C`
        would send the agent to fix a flag it never used."""
        message = self._assert_blocked('cd "$WT" && git commit -m "x"')
        self.assertIn("Cannot determine which repo", message)
        self.assertIn("cd", message)

    @patch("git_commits.is_git_commit", return_value=True)
    def test_command_substitution_cd_is_blocked(self, *_mocks):
        self._assert_blocked('cd "$(git rev-parse --show-toplevel)" && git commit -m x')

    @patch("git_commits.is_git_commit", return_value=True)
    def test_concatenated_quoting_cd_is_blocked(self, *_mocks):
        self._assert_blocked("cd '/tmp/'\"$WT\" && git commit -m x")


class TestTheCdBlockDoesNotOverreach(_HookTestCase):
    """Fail-closed must not become fail-often. Each of these must PROCEED."""

    def _run(self, command: str, cwd: str):
        return pre_tool_bash.run(
            _make_bash_input(command=command, cwd=cwd), smm_dir=self.smm_dir
        )

    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("commits.get_staged_files", return_value=[])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_a_quoted_literal_cd_proceeds(self, *_mocks):
        """The form the reachability half just fixed: quoted because the path has
        a space, fully readable, must not be swept up by the refusal."""
        with tempfile.TemporaryDirectory() as base:
            spacey = os.path.join(base, "a real dir")
            os.mkdir(spacey)
            self._run(f'cd "{spacey}" && git commit -m "x"', "/tmp")

    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("commits.get_staged_files", return_value=[])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_a_missing_literal_cd_proceeds(self, *_mocks):
        """The `-C` rule this must not break: the shell's `cd` fails, `&&`
        short-circuits, nothing lands. An ordinary failure, not a refusal."""
        with tempfile.TemporaryDirectory() as base:
            self._run(f"cd {base}/no-such-dir && git commit -m x", "/tmp")

    @patch("commits.get_code_files_for_review", return_value=[])
    @patch("commits.get_staged_files", return_value=[])
    @patch("commits.get_staged_diff", return_value="")
    @patch("git_commits.is_git_commit", return_value=True)
    def test_an_absolute_dash_c_pins_the_target_despite_a_variable_cd(self, *_mocks):
        """The narrowing, end to end. `-C` beats `cd` and an absolute `-C` is
        unaffected by wherever the shell moved, so the destination is known."""
        with tempfile.TemporaryDirectory() as repo:
            self._run(f'cd "$WT" && git -C {repo} commit -m "x"', "/tmp")


if __name__ == "__main__":
    unittest.main()
