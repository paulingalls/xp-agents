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

    def test_parse_effective_cwd_resolves_a_QUOTED_literal_path(self):
        """A quoted literal `-C` path must resolve to that path.

        The defect this story exists to close, and the reason it survived: every
        other quoted-`-C` fixture in the suite uses a path that is unresolvable
        either way (`$WT`, `~/wt`, `wt*`), so none of them could tell a correct
        parse from one that silently returned the caller's cwd.

        `parse_effective_cwd` scanned `strip_quoted(command)`, which DELETES the
        quoted span and its delimiters — `git -C "/p" commit` becomes
        `git -C  commit`, so the regex captured the literal token `commit` as the
        path, failed `is_dir()`, and fell through to the fallback. Its two
        siblings (`dash_c_unreachable`, `head_probe_target`) already read the path
        from the RAW command via the offset-preserving mask; this function was
        the one never migrated.

        Both quote styles, because the raw-token regex has a separate
        alternation branch for each.
        """
        with tempfile.TemporaryDirectory() as tmp:
            commands = (
                f'git -C "{tmp}" commit -m x',
                f"git -C '{tmp}' commit -m x",
            )
            for command in commands:
                with self.subTest(command=command):
                    self.assertEqual(
                        commit_command.parse_effective_cwd(command, "/HOOK/CWD"), tmp
                    )

    def test_a_quoted_literal_path_is_not_refused(self):
        """The other half of the same fix: resolving it must not also refuse it.

        A quoted literal path carries no shell construct, so widening the
        refusal to cover the parse's old blind spot would trade a silent
        wrong-repo scan for a loud obstruction on the documented
        `git -C <path>` teammate form — which MUST be quoted when the path
        contains a space.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(
                commit_command.dash_c_unreachable(f'git -C "{tmp}" commit -m x')
            )

    def test_head_probe_target_agrees_on_a_quoted_path(self):
        """Extends the existing agreement pin to the quoted form.

        The two functions disagreeing about which repo a commit lands in is the
        root cause here, so the agreement is pinned for the shape that broke it,
        not only for the bare shape that always worked.
        """
        with tempfile.TemporaryDirectory() as tmp:
            command = f'git -C "{tmp}" commit -m x'
            self.assertEqual(
                commit_command.head_probe_target(command, "/HOOK/CWD"),
                commit_command.parse_effective_cwd(command, "/HOOK/CWD"),
            )

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

    def test_a_MIXED_quoting_token_is_unreachable(self):
        """`-C '/tmp/'"$WT"` is two concatenated segments, and only the first is
        captured — so the path as a whole was never recovered.

        `_token_unreachable` judges by the captured segment's quoting, and
        single-quoted means "the shell expanded nothing", which is true of
        `/tmp/` and irrelevant to the `"$WT"` that follows it. Previously
        recorded as a deliberate known limit; it is a live hole, because the
        concatenation can name a real repo the hook never sees.

        This became MORE dangerous once parse_effective_cwd started reading raw
        tokens: it now resolves confidently to the first segment's directory
        rather than falling back, so a gate scans a real-but-wrong repo.
        """
        for command in (
            """git -C '/tmp/'"$WT" commit -m x""",
            """git -C "/tmp/"'$WT' commit -m x""",
            """git -C '/tmp/'"$(pwd)" commit -m x""",
        ):
            with self.subTest(command=command):
                self.assertTrue(commit_command.dash_c_unreachable(command))

    def test_every_ordinary_quoted_form_stays_reachable(self):
        """The non-vacuity guard for the check above.

        A recoverability test that refused every quoted token would satisfy the
        mixed-form assertion and break the documented `git -C <path>` form that
        MUST be quoted when the path contains a space. Each of these is a single
        fully-recovered token and must stay reachable.
        """
        with tempfile.TemporaryDirectory() as tmp:
            spaced = Path(tmp) / "a dir with spaces"
            spaced.mkdir()
            for command in (
                f'git -C "{tmp}" commit -m x',
                f"git -C '{tmp}' commit -m x",
                f'git -C "{spaced}" commit -m x',
                'git -C "~/wt" commit -m x',
                "git -C '$WT' commit -m x",
                "git -C /nonexistent/repo commit -m x",
            ):
                with self.subTest(command=command):
                    self.assertFalse(commit_command.dash_c_unreachable(command))

    def test_no_dash_c_spelling_proceeds_against_a_repo_it_did_not_name(self):
        """AC-3, pinned as the defect CLASS rather than its instances.

        The class is: **the gate proceeds while scanning a repo the command did
        not name.** Every instance of this bug is a member of it, so pinning the
        class catches the next spelling nobody thought of.

        Two things this deliberately does NOT do, both of which I got wrong on
        the first attempt and only caught by tracing every row:

        - It does not use one directory as both the fallback and the target. Doing
          so makes a CORRECT resolution indistinguishable from a fallback, and
          all three recoverable spellings read as failures.
        - It does not treat "resolved to something" as success. The mixed-quoting
          token resolves confidently to its first segment — a real directory that
          is not the target — so a `resolved != fallback` check scores the worst
          case as a pass. The assertion is `resolved == the named repo`.

        `expected is None` means the hook cannot know the target, which must
        produce a refusal rather than a scan.

        ONE documented exception, asserted rather than skipped: a fully-recovered
        bare literal path that does not exist. git aborts on it, so nothing lands
        anywhere and the fallback is harmless — commit_handling.py:158-162,
        pinned end-to-end at test_trailer_linkage.py:217-230.
        """
        with tempfile.TemporaryDirectory() as td:
            caller = Path(td) / "caller"
            caller.mkdir()
            target = Path(td) / "target"
            target.mkdir()
            fallback = str(caller)
            cases = (
                (f'git -C "{target}" commit -m x', str(target)),
                (f"git -C '{target}' commit -m x", str(target)),
                (f"git -C {target} commit -m x", str(target)),
                ('git -C "$WT" commit -m x', None),
                ("git -C ${WT} commit -m x", None),
                ('git -C "$(pwd)" commit -m x', None),
                ("git -C ~/wt commit -m x", None),
                ("git -C wt* commit -m x", None),
                ("""git -C '/tmp/'"$WT" commit -m x""", None),
            )
            for command, expected in cases:
                with self.subTest(command=command):
                    refused = commit_command.dash_c_unreachable(command)
                    resolved = commit_command.parse_effective_cwd(command, fallback)
                    if expected is None:
                        self.assertTrue(
                            refused,
                            "target unknowable to the hook, yet not refused — "
                            "the gate would scan some other repo",
                        )
                    else:
                        self.assertFalse(refused)
                        self.assertEqual(resolved, expected)

            absent = "git -C /nonexistent/repo commit -m x"
            self.assertFalse(commit_command.dash_c_unreachable(absent))
            self.assertEqual(
                commit_command.parse_effective_cwd(absent, fallback), fallback
            )

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


if __name__ == "__main__":
    unittest.main()
