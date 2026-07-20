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
import git_commits


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


class TestParseEffectiveCwdScanTarget(unittest.TestCase):
    """story-007: parse_effective_cwd accepts a pre-stripped scan_target so
    callers (bash_post_tool) that already have one don't pay for a second
    strip_quoted scan. Default behavior (scan_target=None) preserves the
    self-stripping path."""

    def test_default_strips_internally(self):
        """Omitting scan_target keeps the heredoc-immune behavior — quoted
        `cd /tmp` inside a commit message must NOT retarget cwd."""
        with tempfile.TemporaryDirectory() as outer:
            command = (
                f"cd {outer} && git commit -m \"$(cat <<'EOF'\n"
                'subject\n\ncd /tmp && rm -rf workspace\nEOF\n)"'
            )
            self.assertEqual(commits.parse_effective_cwd(command, fallback="/"), outer)

    def test_pre_stripped_scan_target_honored(self):
        """A caller-supplied scan_target is consulted directly — the function
        does not re-strip command. Pinned by passing the canonical strip
        result from git_commits.strip_quoted."""
        with tempfile.TemporaryDirectory() as outer:
            command = f"cd {outer} && git commit -m 'subject'"
            scan_target = git_commits.strip_quoted(command)
            self.assertEqual(
                commits.parse_effective_cwd(
                    command, fallback="/", scan_target=scan_target
                ),
                outer,
            )

    def test_pre_stripped_scan_target_takes_precedence(self):
        """When scan_target is provided, it's the SCAN; the function does
        not re-strip command. Pass an empty scan_target and prove the
        cd-token in the original command is not consulted."""
        with tempfile.TemporaryDirectory() as outer:
            command = f"cd {outer} && git commit"
            self.assertEqual(
                commits.parse_effective_cwd(command, fallback="/tmp", scan_target=""),
                "/tmp",
            )


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
