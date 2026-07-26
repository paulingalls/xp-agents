#!/usr/bin/env python3
"""Direct-import tests for scripts/commit_command.py.

Exhaustive coverage of these behaviors already lives in test_commits.py,
which reaches them through commits.py's re-export. These tests pin that
commit_command is independently importable and behaves correctly when
imported directly, not merely through the re-export.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commit_command


class TestCommitCommandDirectImport(unittest.TestCase):
    def test_parse_effective_cwd_git_dash_c(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = commit_command.parse_effective_cwd(
                f"git -C {tmp} commit -m 'msg'", "/fallback"
            )
            self.assertEqual(result, tmp)

    def test_parse_effective_cwd_no_match_returns_fallback(self):
        result = commit_command.parse_effective_cwd("git status", "/fallback")
        self.assertEqual(result, "/fallback")

    def test_dash_c_unreachable_true_for_variable(self):
        self.assertTrue(commit_command.dash_c_unreachable('git -C "$WT" commit'))

    def test_dash_c_unreachable_false_for_literal_path(self):
        self.assertFalse(commit_command.dash_c_unreachable("git -C /tmp/repo commit"))

    def test_dash_c_unreachable_true_for_unquoted_tilde(self):
        """A BARE ~ is expanded by the shell, so git lands where the hook can't see."""
        self.assertTrue(commit_command.dash_c_unreachable("git -C ~/wt commit"))

    def test_dash_c_unreachable_false_for_quoted_tilde(self):
        """Quoting defeats tilde expansion: git receives a literal `~/wt`, aborts,
        and nothing lands — the same silent case as any other literal bad path."""
        self.assertFalse(commit_command.dash_c_unreachable('git -C "~/wt" commit'))
        self.assertFalse(commit_command.dash_c_unreachable("git -C '~/wt' commit"))

    def test_dash_c_unreachable_false_for_tilde_inside_path(self):
        """Only a LEADING tilde expands; `/tmp/a~b` is an ordinary literal path."""
        self.assertFalse(commit_command.dash_c_unreachable("git -C /tmp/a~b commit"))

    def test_dash_c_unreachable_true_for_brace_and_substitution(self):
        self.assertTrue(commit_command.dash_c_unreachable("git -C ${W} commit"))
        self.assertTrue(commit_command.dash_c_unreachable("git -C $(pwd) commit"))

    def test_dash_c_unreachable_false_for_single_quoted_variable(self):
        """Single quotes suppress expansion entirely, so git gets a literal `$WT`
        and aborts — the same must-stay-silent case as a literal bad path. Judged
        by quoting, not by the mere presence of a `$`."""
        self.assertFalse(commit_command.dash_c_unreachable("git -C '$WT' commit"))
        self.assertFalse(commit_command.dash_c_unreachable("git -C '$(pwd)' commit"))

    def test_dash_c_unreachable_true_for_double_quoted_variable(self):
        """Double quotes still expand `$` and backticks."""
        self.assertTrue(commit_command.dash_c_unreachable('git -C "$WT" commit'))
        self.assertTrue(commit_command.dash_c_unreachable('git -C "$(pwd)" commit'))

    def test_dash_c_unreachable_false_when_only_the_message_mentions_dash_c(self):
        """A commit whose MESSAGE talks about `git -C $VAR` carries no `-C` flag.
        Presence is decided on the quote-stripped command, so documenting the
        gate never trips it."""
        self.assertFalse(
            commit_command.dash_c_unreachable(
                'git commit -m "docs: prefer git -C $WT over cd"'
            )
        )
        self.assertFalse(
            commit_command.dash_c_unreachable(
                'git commit -m "docs: prefer git -C ~/wt over cd"'
            )
        )

    def test_dash_c_unreachable_false_when_heredoc_body_mentions_dash_c(self):
        """`strip_quoted` drops heredocs too — a commit body written on stdin
        can discuss `-C` without being read as one."""
        self.assertFalse(
            commit_command.dash_c_unreachable(
                "git commit -F - <<'EOF'\ndocs: prefer git -C $WT\nEOF"
            )
        )

    def test_is_escape_hatch_commit_true(self):
        self.assertTrue(
            commit_command.is_escape_hatch_commit('git commit -m "[chore] tidy up"')
        )

    def test_is_escape_hatch_commit_false(self):
        self.assertFalse(
            commit_command.is_escape_hatch_commit('git commit -m "WIP fix"')
        )

    def test_extract_commit_message_simple(self):
        self.assertEqual(
            commit_command.extract_commit_message('git commit -m "hello world"'),
            "hello world",
        )

    def test_extract_commit_message_none(self):
        self.assertIsNone(commit_command.extract_commit_message("git status"))


class TestStdinHeredocFormsUnchanged(unittest.TestCase):
    """AC-3: the forms that already parse today must stay byte-identical
    after the pattern change. Direct-import parser-shape fixtures — the
    redirect/pipe/earlier-heredoc regressions live in test_commit_handling.py
    (imported through `commits`, not `commit_command` directly)."""

    def test_clean_quoted_delimiter(self):
        command = "git commit -q -F - <<'EOF'\nfeat: clean\nEOF"
        self.assertEqual(commit_command.extract_commit_message(command), "feat: clean")

    def test_unquoted_delimiter(self):
        command = "git commit -q -F - <<EOF\nfeat: unquoted\nEOF"
        self.assertEqual(
            commit_command.extract_commit_message(command), "feat: unquoted"
        )

    def test_whitespace_padded_delimiter(self):
        command = "git commit -q -F - <<   'EOF'\nfeat: padded\nEOF"
        self.assertEqual(commit_command.extract_commit_message(command), "feat: padded")


class TestStdinHeredocClosingTruncation(unittest.TestCase):
    """Row 3 of the story's repro table: a body LINE that merely starts
    with the delimiter word (a prefix, not the delimiter itself) must not
    end the heredoc early. Pinned at the parser's own contract — the
    `extract_commit_message` docstring promises to "recover the message a
    git command supplied", and returning a silently truncated prefix breaks
    that promise regardless of which downstream consumer currently notices.

    (Empirically checked against pre_tool_bash.py's two PreToolUse
    consumers of this parser -- `parse_verify_deferred` and
    `is_escape_hatch_commit` -- both anchor on the message's START, so a
    tail truncation from this specific defect does not change their output;
    a test pinning either would pass identically before and after this fix,
    proving nothing, the same flaw already identified in the confirmation
    fallback. See concern recorded against 033daa426553.)
    """

    def test_body_line_prefixed_by_delimiter_is_not_mistaken_for_close(self):
        command = (
            "git commit -q -F - <<'EOF'\n"
            "Subject\n"
            "\n"
            "EOF_NOT_THE_END: still part of the body\n"
            "EOF"
        )
        self.assertEqual(
            commit_command.extract_commit_message(command),
            "Subject\n\nEOF_NOT_THE_END: still part of the body",
        )


class TestStdinHeredocWhitespaceToleranceBothDirections(unittest.TestCase):
    """What the discarded `[ \t]*` draft got wrong, measured against bash:
    plain `<<` terminates only at column 0; `<<-` terminates on leading
    TABS, never spaces. Neither direction may accept the other's
    whitespace, or a body line that merely looks like an indented close
    truncates the message early -- the same defect class, reintroduced."""

    def test_plain_heredoc_ignores_tab_indented_body_delimiter_line(self):
        command = "git commit -q -F - <<'EOF'\nSubject\n\tEOF\nmore body\nEOF"
        self.assertEqual(
            commit_command.extract_commit_message(command),
            "Subject\n\tEOF\nmore body",
        )

    def test_dash_heredoc_ignores_space_indented_body_delimiter_line(self):
        command = "git commit -q -F - <<-'EOF'\nSubject\n EOF\nmore body\nEOF"
        self.assertEqual(
            commit_command.extract_commit_message(command),
            "Subject\n EOF\nmore body",
        )


class TestStdinHeredocDashFormNetNew(unittest.TestCase):
    """The `<<-` form has zero fixtures in the suite before this story --
    a tab-indented closing delimiter returns None today. Red-first, not a
    before/after equality pin."""

    def test_dash_heredoc_tab_indented_close_recovers(self):
        command = "git commit -q -F - <<-'EOF'\nfeat: dash form\n\tEOF"
        self.assertEqual(
            commit_command.extract_commit_message(command), "feat: dash form"
        )

    def test_dash_heredoc_strips_body_leading_tabs(self):
        """`<<-` strips leading tabs from EVERY body line, not just the
        closing delimiter line -- the extracted message must match what git
        actually stored, not the raw indented source text."""
        command = (
            "git commit -q -F - <<-'EOF'\n"
            "\tfeat: dash form\n"
            "\n"
            "\tBody line, indented in source.\n"
            "\tEOF"
        )
        self.assertEqual(
            commit_command.extract_commit_message(command),
            "feat: dash form\n\nBody line, indented in source.",
        )


if __name__ == "__main__":
    unittest.main()
