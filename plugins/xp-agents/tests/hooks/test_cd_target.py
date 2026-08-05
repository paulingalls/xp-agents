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
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commit_command


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


if __name__ == "__main__":
    unittest.main()
