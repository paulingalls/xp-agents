#!/usr/bin/env python3
"""Which `-m`/`-F` forms the SHELL expands, and what the rebuild guard reads.

The rebuild's sharpest guard is "a message the hook CAN read is evidence this
command did not make HEAD". It was decided by scanning the recovered text for
`$` or a backtick — with no idea which QUOTING the text arrived in. A
single-quoted subject containing a literal backtick (this project's own
subjects routinely do) therefore read as "unexpanded", every other guard
passed, and `rebuild_at_head` fabricated a `type=commit` event for a commit the
command never made — honouring THAT commit's `Resolves-Event:` trailer, so
concerns closed on evidence from someone else's work.

Which constructs actually expand is a property of the quoting, exactly as
`commit_command._token_unreachable` already judges a `-C` path. So the form is
recovered alongside the message and the guard reads both.
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commit_emit
import commit_message
from test_commit_event_rebuild import _RebuildTestCase

# A subject with a literal backtick and one with a literal `$`: both are
# ordinary prose in this repo's own history, and git stored both verbatim.
_BACKTICK_SUBJECT = "Sanitize `the line`, not one field"
_DOLLAR_SUBJECT = "reduce cost to $5 per run"


def _heredoc(delimiter_quote: str, body: str) -> str:
    """A `-m "$(cat <<EOF …)"` command, delimiter quoted or not."""
    q = delimiter_quote
    return f'git commit -m "$(cat <<{q}EOF{q}\n{body}\nEOF\n)"'


class TestRecoveredForm(unittest.TestCase):
    """`recover_commit_message` reports the message AND whether the shell
    expanded the form it arrived in."""

    def test_single_quoted_is_verbatim(self):
        message, expands = commit_message.recover_commit_message(
            f"git commit -m '{_BACKTICK_SUBJECT}'"
        )
        self.assertEqual(message, _BACKTICK_SUBJECT)
        self.assertFalse(expands)

    def test_double_quoted_expands(self):
        message, expands = commit_message.recover_commit_message('git commit -m "$MSG"')
        self.assertEqual(message, "$MSG")
        self.assertTrue(expands)

    def test_quoted_heredoc_delimiter_is_verbatim(self):
        message, expands = commit_message.recover_commit_message(
            _heredoc("'", _BACKTICK_SUBJECT)
        )
        self.assertEqual(message, _BACKTICK_SUBJECT)
        self.assertFalse(expands)

    def test_unquoted_heredoc_delimiter_expands(self):
        message, expands = commit_message.recover_commit_message(
            _heredoc("", "release $VERSION")
        )
        self.assertEqual(message, "release $VERSION")
        self.assertTrue(expands)

    def test_stdin_heredoc_follows_its_delimiter_quoting(self):
        quoted = "git commit -F - <<'EOF'\n" + _BACKTICK_SUBJECT + "\nEOF"
        bare = "git commit -F - <<EOF\nrelease $VERSION\nEOF"
        self.assertEqual(
            commit_message.recover_commit_message(quoted),
            (_BACKTICK_SUBJECT, False),
        )
        self.assertEqual(
            commit_message.recover_commit_message(bare),
            ("release $VERSION", True),
        )

    def test_message_file_content_is_verbatim(self):
        """git reads the file's bytes; nothing in it was ever expanded."""
        tmp = Path(tempfile.mkdtemp())
        try:
            path = tmp / "MSG"
            path.write_text(_DOLLAR_SUBJECT, encoding="utf-8")
            self.assertEqual(
                commit_message.recover_commit_message(f"git commit -F {path}"),
                (_DOLLAR_SUBJECT, False),
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_message_recovers_nothing(self):
        self.assertEqual(
            commit_message.recover_commit_message("git commit -F /nope/gone"),
            (None, False),
        )

    def test_extract_commit_message_still_returns_just_the_message(self):
        """The historical single-value entry point every caller uses."""
        self.assertEqual(
            commit_message.extract_commit_message(f"git commit -m '{_DOLLAR_SUBJECT}'"),
            _DOLLAR_SUBJECT,
        )


class TestUnreadableFromCommand(unittest.TestCase):
    """The rebuild guard. False = "the hook read the real message", which is
    evidence AGAINST recording; True opens the rebuild."""

    def assert_readable(self, command: str) -> None:
        self.assertFalse(
            commit_emit._message_unreadable_from_command(command),
            f"judged unreadable, so the rebuild is armed for: {command!r}",
        )

    def test_literal_backtick_in_a_single_quoted_subject_is_readable(self):
        self.assert_readable(f"git commit -m '{_BACKTICK_SUBJECT}'")

    def test_literal_dollar_in_a_single_quoted_subject_is_readable(self):
        self.assert_readable(f"git commit -m '{_DOLLAR_SUBJECT}'")

    def test_backtick_in_a_quoted_heredoc_is_readable(self):
        self.assert_readable(_heredoc("'", f"{_BACKTICK_SUBJECT}\n\nbody"))

    def test_plain_subject_is_readable(self):
        self.assert_readable("git commit -m 'a subject that never landed'")

    def test_shell_variable_in_a_double_quoted_message_is_unreadable(self):
        self.assertTrue(
            commit_emit._message_unreadable_from_command('git commit -m "$MSG"')
        )

    def test_substitution_in_an_unquoted_heredoc_is_unreadable(self):
        self.assertTrue(
            commit_emit._message_unreadable_from_command(
                _heredoc("", "release $(cat VERSION)")
            )
        )

    def test_no_recoverable_message_is_unreadable(self):
        self.assertTrue(
            commit_emit._message_unreadable_from_command("git commit -F /gone/MSG")
        )


class TestLiteralSubjectIsNotRebuilt(_RebuildTestCase):
    """The end-to-end hole: the sibling `readable message that missed` case,
    with a backtick in the subject. HEAD is fresh, single-parent and reflogged
    as `commit`, so those three guards pass; only the readable-message check
    stands between the hook and an event for a commit this command never made.
    """

    def test_backtick_subject_that_missed_records_no_commit_event(self):
        self.commit("feat: history that predates this command")
        self.run_hook(f"git commit -m '{_BACKTICK_SUBJECT}'")
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(len(self.concerns()), 1)


if __name__ == "__main__":
    unittest.main()
