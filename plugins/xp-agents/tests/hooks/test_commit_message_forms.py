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
`dash_c_tokens.token_unreachable` already judges a `-C` path. So the form is
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


class TestAHeredocBodyDoesNotSupplyTheMessage(unittest.TestCase):
    """A `-m` token inside a stdin-fed BODY is prose, not an argument.

    `recover_commit_message` searched the simple `-m` pattern across the whole
    command string before it ever reached the `-F -` branch, so a body
    mentioning a runner flag supplied the message. The damage is not a wrong
    string: the recovered text then fails to match HEAD's subject, so NO commit
    event is written at all, a `Resolves-Event:` trailer never links, and an
    escape-hatch prefix in the real subject is invisible to the branch guard.
    """

    _SUBJECT = "Real subject here"

    def _stdin_commit(self, body: str, *, delimiter: str = "MSG") -> str:
        return f"git commit -F - <<'{delimiter}'\n{body}\n{delimiter}"

    def test_a_runner_flag_in_the_body_is_not_the_message(self):
        command = self._stdin_commit(
            f'{self._SUBJECT}\n\nRan pytest -m "slow" to check.'
        )
        message, _ = commit_message.recover_commit_message(command)
        self.assertIsNotNone(message)
        self.assertTrue((message or "").startswith(self._SUBJECT))
        self.assertNotEqual(message, "slow")

    def test_a_body_that_mentions_its_own_delimiter_still_holds(self):
        """The strict span matters. A helper that terminates at the delimiter
        WORD anywhere leaves the rest of the body exposed, so a body discussing
        its own delimiter would still leak the `-m` after it."""
        command = self._stdin_commit(
            f'{self._SUBJECT}\n\nDiscussed the MSG format; ran pytest -m "slow".'
        )
        message, _ = commit_message.recover_commit_message(command)
        self.assertTrue((message or "").startswith(self._SUBJECT))
        self.assertNotEqual(message, "slow")

    def test_the_dash_form_body_is_also_protected(self):
        command = (
            f'git commit -F - <<-MSG\n\t{self._SUBJECT}\n\tpytest -m "slow"\n\tMSG'
        )
        message, _ = commit_message.recover_commit_message(command)
        self.assertTrue((message or "").startswith(self._SUBJECT))
        self.assertNotEqual(message, "slow")

    def test_an_escape_hatch_prefix_in_a_stdin_subject_is_seen(self):
        command = self._stdin_commit('[sprint-direct] Real work\n\npytest -m "slow"')
        self.assertTrue(commit_message.is_escape_hatch_commit(command))

    def test_an_earlier_unrelated_heredoc_does_not_capture_the_message(self):
        command = (
            "cat <<CFG > cfg.ini\n"
            'runner = pytest -m "slow"\n'
            "CFG\n"
            f"git commit -F - <<'MSG'\n{self._SUBJECT}\nMSG"
        )
        message, _ = commit_message.recover_commit_message(command)
        self.assertEqual(message, self._SUBJECT)


class TestTheOrdinaryFormsAreUnchanged(unittest.TestCase):
    """The regression guard for the subtraction's ORDER.

    `_HEREDOC_MSG_RE` must keep matching the ORIGINAL command: it is itself a
    heredoc form, so subtracting bodies first would delete the very body it
    captures. Only the simple-`-m` search moves onto stripped text.
    """

    def test_the_cat_heredoc_form_still_returns_its_whole_body(self):
        body = 'Subject line\n\nRan pytest -m "slow" while testing.'
        message, expands = commit_message.recover_commit_message(_heredoc("'", body))
        self.assertEqual(message, body)
        self.assertFalse(expands)

    def test_a_plain_single_quoted_message_is_unchanged(self):
        message, expands = commit_message.recover_commit_message(
            f"git commit -m '{_DOLLAR_SUBJECT}'"
        )
        self.assertEqual(message, _DOLLAR_SUBJECT)
        self.assertFalse(expands)

    def test_a_plain_double_quoted_message_still_reports_expansion(self):
        message, expands = commit_message.recover_commit_message(
            'git commit -m "subject with $VAR"'
        )
        self.assertEqual(message, "subject with $VAR")
        self.assertTrue(expands)

    def test_a_real_message_wins_over_a_heredoc_later_in_the_command(self):
        command = (
            'git commit -m "the real subject" && cat <<CFG > c.ini\n'
            'x = pytest -m "fake"\n'
            "CFG"
        )
        message, _ = commit_message.recover_commit_message(command)
        self.assertEqual(message, "the real subject")


if __name__ == "__main__":
    unittest.main()
