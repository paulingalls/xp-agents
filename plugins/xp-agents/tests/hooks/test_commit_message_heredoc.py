#!/usr/bin/env python3
"""Commit-message recovery from a `-F -` stdin heredoc.

Extracted from `test_commit_command.py`, which crossed the 500-line cap when
story-011 added its `-C` target coverage. The split follows the module boundary
that already exists in production: `commit_message.py` owns message recovery,
`commit_command.py` owns the `-C` target and reachability judgements, and its
test file should claim only the latter — as its own docstring says it does.

These are direct-import parser-shape fixtures. The redirect/pipe/earlier-heredoc
regressions live in `test_commit_handling.py` (imported through `commits`, not
`commit_command` directly).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commit_command


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
