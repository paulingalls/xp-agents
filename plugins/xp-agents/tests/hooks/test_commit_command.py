#!/usr/bin/env python3
"""Direct-import tests for scripts/commit_command.py.

Two jobs. It pins that commit_command is independently importable and behaves
correctly when imported directly, not merely through commits.py's re-export;
and it is the unit home for the module's own predicates — `parse_effective_cwd`
and `dash_c_unreachable` case-by-case. The behaviour those predicates drive
(what the commit gate blocks) is pinned end-to-end in
test_pre_tool_bash_git_c_target.py instead.
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

    def test_parse_effective_cwd_relative_dash_c_resolves_against_fallback(self):
        """A RELATIVE literal `-C` path must keep resolving exactly as it does
        today, against the caller's cwd.

        Green before and after the fail-closed refusal landed — a pin on
        existing behaviour, not a red step. It is here because the refusal
        (`dash_c_unreachable`) keys on shell constructs, and the cheapest way to
        get that wrong is to widen it into a blanket "anything not absolute is
        unresolvable". The absolute case is covered above; a relative path
        reaches a DIFFERENT branch of `_resolve` (the `Path(fallback) / path`
        join), so absolute coverage alone would not catch that widening.
        """
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "wt").mkdir()
            result = commit_command.parse_effective_cwd(
                "git -C wt commit -m 'msg'", tmp
            )
            self.assertEqual(result, str(Path(tmp) / "wt"))

    def test_relative_dash_c_is_not_treated_as_unreachable(self):
        """The other half: a relative literal path carries no shell construct,
        so the commit gate must let it proceed rather than refuse it."""
        self.assertFalse(commit_command.dash_c_unreachable("git -C wt commit"))
        self.assertFalse(commit_command.dash_c_unreachable("git -C ./wt commit"))
        self.assertFalse(commit_command.dash_c_unreachable("git -C ../sibling commit"))

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

    def test_dash_c_unreachable_true_for_unquoted_glob(self):
        """An UNQUOTED glob expands too, and unlike a bad literal it does not
        abort: the shell hands git a real directory while the hook still sees
        the pattern, `is_dir()` fails, and every gate reads the caller's repo.
        Same bypass as `$WT`, so the same refusal."""
        self.assertTrue(commit_command.dash_c_unreachable("git -C wt* commit"))
        self.assertTrue(
            commit_command.dash_c_unreachable("git -C ../worktree-story-1?? commit")
        )
        self.assertTrue(commit_command.dash_c_unreachable("git -C /tmp/w[12] commit"))

    def test_dash_c_unreachable_false_for_quoted_glob(self):
        """Quoting suppresses globbing, so git receives the literal pattern and
        aborts — nothing lands, nothing to fail closed over."""
        self.assertFalse(commit_command.dash_c_unreachable('git -C "wt*" commit'))
        self.assertFalse(commit_command.dash_c_unreachable("git -C 'wt*' commit"))

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

    def test_dash_c_unreachable_true_when_a_LATER_token_is_hidden(self):
        """The bypass: stage in a literal repo, commit in a hidden one.

        Reading only the FIRST `-C` match judged `/literal` — no shell
        construct, so reachable — while `parse_effective_cwd` resolved the LAST
        one and every gate scanned the repo the commit never landed in. Nothing
        here can attribute a `-C` to the `commit` word, so ANY unreachable
        target means the destination is unknowable.
        """
        self.assertTrue(
            commit_command.dash_c_unreachable(
                'git -C /Users/me/repo add -A && git -C "$WT" commit -m "fix"'
            )
        )
        self.assertTrue(
            commit_command.dash_c_unreachable(
                "git -C /Users/me/repo add -A && git -C ~/wt commit -m 'fix'"
            )
        )
        self.assertTrue(
            commit_command.dash_c_unreachable(
                "git -C /a add -A; git -C /b diff; git -C $(pwd) commit -m 'x'"
            )
        )

    def test_dash_c_unreachable_false_when_every_token_is_literal(self):
        """The other half: a chain of literal targets must still not be refused."""
        self.assertFalse(
            commit_command.dash_c_unreachable(
                "git -C /Users/me/repo add -A && git -C /Users/me/repo commit -m 'fix'"
            )
        )

    def test_a_real_dash_c_plus_a_message_that_mentions_one_is_not_refused(self):
        """Per-token scanning must not read the MESSAGE as a second token.

        This repo's own commit messages discuss `git -C "$WT"` constantly, and
        `-C /literal commit -m "…$WT…"` is the shape that would be refused if
        the scan ran over the raw command instead of the offset-preserving mask.
        """
        self.assertFalse(
            commit_command.dash_c_unreachable(
                'git -C /Users/me/repo commit -m "docs: prefer git -C $WT over cd"'
            )
        )
        self.assertFalse(
            commit_command.dash_c_unreachable(
                "git -C /Users/me/repo commit -F - <<'EOF'\ndocs: git -C ~/wt\nEOF"
            )
        )
        self.assertFalse(
            commit_command.dash_c_unreachable(
                'git -C /Users/me/repo commit -m "escaped \\"git -C $WT\\" quote"'
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

    def test_head_probe_target_agrees_with_parse_effective_cwd_on_which_dash_c(self):
        """Both functions answer "which repo did this command target", and a
        compound command made them answer different ends of it.

        `parse_effective_cwd` takes the LAST validated `-C`; the probe took the
        FIRST match, so `git -C /a add && git -C /b commit` was probed in /a. If
        an earlier commit had advanced /a's HEAD, that fabricates the head-moved
        trace the "not a dir -> None" arm is careful never to fabricate.
        """
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            a.mkdir()
            b.mkdir()
            command = f"git -C {a} add -A && git -C {b} commit -m 'msg'"
            self.assertEqual(
                commit_command.head_probe_target(command, tmp),
                commit_command.parse_effective_cwd(command, tmp),
            )
            self.assertEqual(commit_command.head_probe_target(command, tmp), str(b))

    def test_head_probe_target_ignores_a_dash_c_inside_the_message(self):
        """The probe reads the LAST token, so the mask is what keeps a message
        body from becoming the target it reads."""
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            command = f'git -C {real} commit -m "prefer git -C /elsewhere over cd"'
            self.assertEqual(commit_command.head_probe_target(command, tmp), str(real))

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
