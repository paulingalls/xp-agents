#!/usr/bin/env python3
"""Tests for scripts/commits.py: command-string level parsing -- extracting
the -m message from a git commit shell command, classifying escape-hatch
prefixes, and resolving the effective cwd of a commit invocation.

Split from test_commits.py -- these operate on the raw bash command string
rather than a commit message body already handed to them.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commits


class TestExtractCommitMessage(unittest.TestCase):
    def test_double_quoted(self):
        self.assertEqual(
            commits.extract_commit_message('git commit -m "fix bug"'),
            "fix bug",
        )

    def test_single_quoted(self):
        self.assertEqual(
            commits.extract_commit_message("git commit -m 'add feature'"),
            "add feature",
        )

    def test_no_m_flag(self):
        self.assertIsNone(commits.extract_commit_message("git commit"))

    def test_heredoc_style(self):
        cmd = """git commit -m "$(cat <<'EOF'
[release] bump version

Co-Authored-By: Claude
EOF
)" """
        result = commits.extract_commit_message(cmd)
        assert result is not None
        self.assertTrue(result.startswith("[release]"))

    def test_empty_message(self):
        self.assertEqual(
            commits.extract_commit_message('git commit -m ""'),
            "",
        )

    def test_message_with_special_chars(self):
        self.assertEqual(
            commits.extract_commit_message('git commit -m "[chore] update deps"'),
            "[chore] update deps",
        )


class TestIsEscapeHatchCommit(unittest.TestCase):
    def test_release_prefix(self):
        self.assertTrue(
            commits.is_escape_hatch_commit('git commit -m "[release] v1.0"')
        )

    def test_chore_prefix(self):
        self.assertTrue(
            commits.is_escape_hatch_commit('git commit -m "[chore] cleanup"')
        )

    def test_sprint_direct_prefix(self):
        # Constraint b2467c56ddbf names [sprint-direct] as the close-window
        # bypass token. More honest than [chore] for direct-to-sprint work.
        self.assertTrue(
            commits.is_escape_hatch_commit(
                'git commit -m "[sprint-direct] post-merge cleanup"'
            )
        )

    def test_case_insensitive(self):
        self.assertTrue(
            commits.is_escape_hatch_commit('git commit -m "[Release] v2.0"')
        )

    def test_no_prefix(self):
        self.assertFalse(commits.is_escape_hatch_commit('git commit -m "fix bug"'))

    def test_no_m_flag(self):
        self.assertFalse(commits.is_escape_hatch_commit("git commit"))

    def test_prefix_not_at_start(self):
        self.assertFalse(
            commits.is_escape_hatch_commit('git commit -m "fix [release] tag"')
        )


class TestIsEscapeHatchMessage(unittest.TestCase):
    """Message-level escape-hatch check — shared by the commit gate and the
    retro review-required denominator."""

    def test_release_prefix(self):
        self.assertTrue(commits.is_escape_hatch_message("[release] v1.0"))

    def test_chore_and_sprint_direct(self):
        self.assertTrue(commits.is_escape_hatch_message("[chore] cleanup"))
        self.assertTrue(commits.is_escape_hatch_message("[sprint-direct] hotfix"))

    def test_case_insensitive(self):
        self.assertTrue(commits.is_escape_hatch_message("[RELEASE] v2"))

    def test_none_is_false(self):
        self.assertFalse(commits.is_escape_hatch_message(None))

    def test_plain_message_is_false(self):
        self.assertFalse(commits.is_escape_hatch_message("fix bug"))

    def test_prefix_not_at_start_is_false(self):
        self.assertFalse(commits.is_escape_hatch_message("fix [release] tag"))


class TestParseEffectiveCwdReadsTheCommandItself(unittest.TestCase):
    """`parse_effective_cwd` derives its scan from the command, full stop.

    story-007 gave it a `scan_target` kwarg so callers holding a pre-stripped
    command could avoid a second `strip_quoted`. story-013 REMOVED it, and two
    tests that pinned it are deliberately gone rather than adapted: one asserted a
    caller-supplied scan was honoured, the other that an empty `scan_target` made
    the real command's `cd` token go unconsulted. That second property is exactly
    what the parameter had to lose — a kwarg able to silently redirect which text
    the reader scans is the defect class this module family has been paying down,
    and `cd` paths now come from the same masked-locate/raw-read source as `-C`
    ones. Adapting them would have pinned a parameter that can no longer change an
    answer. `head_probe_target` and `commit_repo_candidates` keep their own
    `scan_target` for `HAS_GLOBAL_DASH_C_RE` / `is_git_commit`.

    What must survive is the property those tests were guarding the edges of, and
    it is asserted directly below.
    """

    def test_a_heredoc_message_body_cannot_retarget_cwd(self):
        """The immunity, with no caller cooperation available: a quoted
        `cd /tmp` inside the commit message must not win over the outer `cd`."""
        with tempfile.TemporaryDirectory() as outer:
            command = (
                f"cd {outer} && git commit -m \"$(cat <<'EOF'\n"
                'subject\n\ncd /tmp && rm -rf workspace\nEOF\n)"'
            )
            self.assertEqual(commits.parse_effective_cwd(command, fallback="/"), outer)


class TestNulPathsDocstring(unittest.TestCase):
    """The _nul_paths docstring cites the unambiguous :0:<path> index ref."""

    def test_docstring_cites_unambiguous_index_ref(self):
        # story-007 made the index reads use :0:<path>; this doc leg was missed
        # (debt 91e962cab643). A future reader debugging index reads must see the
        # unambiguous ref, not the stage-ambiguous :<path>.
        doc = commits._nul_paths.__doc__ or ""
        self.assertIn(":0:<path>", doc)
        self.assertNotIn("-e :<path>", doc)


if __name__ == "__main__":
    unittest.main()
