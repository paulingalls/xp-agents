#!/usr/bin/env python3
"""Tests for scripts/commits.py: code file review, uncommitted files, auto-link.

Split from test_commits.py -- issue-matching and file-listing helpers.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import commits
from conftest import _SMMTestCase, make_event
from event_schema import (
    EVENT_TYPE_ASSUMPTION,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)

_SUBPROCESS = "commits.subprocess.run"

# ---------------------------------------------------------------------------
# get_code_files_for_review
# ---------------------------------------------------------------------------


class TestGetCodeFilesForReview(unittest.TestCase):
    """Test code file counting for review cycle gate."""

    @patch(_SUBPROCESS)
    def test_combines_staged_and_since_review(self, mock_run):
        def side_effect(cmd, **_kwargs):
            r = SimpleNamespace(returncode=0, stdout="")
            if "--cached" in cmd:
                r.stdout = "src/a.py\nsrc/b.py\n"
            elif ".." in cmd[-1]:
                r.stdout = "src/b.py\nsrc/c.py\n"
            return r

        mock_run.side_effect = side_effect
        result = commits.get_code_files_for_review("/tmp", "abc123")
        # a.py, b.py (dedup), c.py = 3 code files
        self.assertEqual(sorted(result), ["src/a.py", "src/b.py", "src/c.py"])

    @patch(_SUBPROCESS)
    def test_filters_non_code_files(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "src/app.py\nREADME.md\npackage.json\n"
        result = commits.get_code_files_for_review("/tmp", "abc123")
        self.assertEqual(result, ["src/app.py"])

    @patch(_SUBPROCESS)
    def test_empty_last_review_skips_since_review(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "src/a.py\n"
        result = commits.get_code_files_for_review("/tmp", "")
        self.assertEqual(result, ["src/a.py"])
        # Should only call git diff --cached, not git diff ..HEAD
        self.assertEqual(mock_run.call_count, 1)
        cmd = mock_run.call_args[0][0]
        self.assertIn("--cached", cmd)

    @patch(_SUBPROCESS)
    def test_git_failure_returns_empty(self, mock_run):
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        result = commits.get_code_files_for_review("/tmp", "abc123")
        self.assertEqual(result, [])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_empty(self, _mock):
        result = commits.get_code_files_for_review("/tmp", "abc123")
        self.assertEqual(result, [])

    @patch(_SUBPROCESS)
    def test_git_add_includes_unstaged(self, mock_run):
        """When command has 'git add', also check unstaged changes."""
        call_count = 0

        def side_effect(cmd, **_kwargs):
            nonlocal call_count
            call_count += 1
            r = SimpleNamespace(returncode=0, stdout="")
            if "--cached" in cmd:
                r.stdout = "src/a.py\n"
            elif "--name-only" in cmd and ".." not in cmd[-1]:
                # git diff --name-only (unstaged)
                r.stdout = "src/b.py\n"
            elif ".." in cmd[-1]:
                r.stdout = ""
            return r

        mock_run.side_effect = side_effect
        result = commits.get_code_files_for_review(
            "/tmp",
            "abc123",
            command="git add -A && git commit -m 'test'",
        )
        self.assertIn("src/a.py", result)
        self.assertIn("src/b.py", result)


# ---------------------------------------------------------------------------
# get_uncommitted_code_files
# ---------------------------------------------------------------------------


class TestGetUncommittedCodeFiles(unittest.TestCase):
    """Tests for commits.get_uncommitted_code_files()."""

    @patch(_SUBPROCESS)
    def test_returns_code_files_only(self, mock_run):
        """Filters out non-code files and test files."""
        staged = type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": ("src/app.py\nREADME.md\ntests/test_app.py\n"),
            },
        )()
        unstaged = type("R", (), {"returncode": 0, "stdout": "src/utils.py\n"})()
        mock_run.side_effect = [staged, unstaged]
        result = commits.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, ["src/app.py", "src/utils.py"])

    @patch(_SUBPROCESS)
    def test_empty_on_no_changes(self, mock_run):
        """No changed files -> empty list."""
        empty = type("R", (), {"returncode": 0, "stdout": ""})()
        mock_run.side_effect = [empty, empty]
        result = commits.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, [])

    @patch(_SUBPROCESS)
    def test_deduplicates_staged_and_unstaged(self, mock_run):
        """Same file in both staged and unstaged -> appears once."""
        staged = type("R", (), {"returncode": 0, "stdout": "src/app.py\n"})()
        unstaged = type("R", (), {"returncode": 0, "stdout": "src/app.py\n"})()
        mock_run.side_effect = [staged, unstaged]
        result = commits.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, ["src/app.py"])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_empty(self, _mock):
        """Subprocess failure -> empty list (graceful degradation)."""
        result = commits.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# open_issues_matching_commit
# ---------------------------------------------------------------------------


class TestOpenIssuesMatchingCommit(_SMMTestCase):
    """Unit tests for the commit-auto-link helper."""

    def setUp(self):
        super().setUp()
        self.cwd = str(self.smm_dir)

    def test_returns_concern_with_file_overlap(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        result = commits.open_issues_matching_commit(
            self.smm_dir,
            ["scripts/auth.py", "README.md"],
            self.cwd,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])

    def test_normalizes_path_variants(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["./scripts/auth.py"], self.cwd
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])

    def test_excludes_resolved_concerns(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        decision = make_event(
            EVENT_TYPE_DECISION,
            content="fix auth",
            topic="auth",
            metadata={"resolves": [concern["id"]]},
        )
        _common.append_safe(self.smm_dir, decision)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(result, [])

    def test_excludes_concerns_without_files(self):
        no_files = make_event(EVENT_TYPE_CONCERN, content="no files")
        empty_files = make_event(EVENT_TYPE_CONCERN, content="empty", files=[])
        _common.append_safe(self.smm_dir, no_files)
        _common.append_safe(self.smm_dir, empty_files)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(result, [])

    def test_includes_debt_with_file_overlap(self):
        debt = make_event(
            EVENT_TYPE_DEBT, content="legacy code", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, debt)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], debt["id"])

    def test_excludes_resolved_debt(self):
        debt = make_event(
            EVENT_TYPE_DEBT, content="legacy code", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, debt)
        resolver = make_event(
            EVENT_TYPE_STATUS,
            content="fixed",
            metadata={"resolves": [debt["id"]]},
        )
        _common.append_safe(self.smm_dir, resolver)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(result, [])

    def test_excludes_non_concern_non_debt_events(self):
        question = make_event(
            EVENT_TYPE_QUESTION, content="why?", files=["scripts/auth.py"]
        )
        assumption = make_event(
            EVENT_TYPE_ASSUMPTION, content="guess", files=["scripts/auth.py"]
        )
        for ev in (question, assumption):
            _common.append_safe(self.smm_dir, ev)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(result, [])

    def test_no_overlap_returns_empty(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["README.md"], self.cwd
        )
        self.assertEqual(result, [])

    def test_empty_commit_files_returns_empty(self):
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        result = commits.open_issues_matching_commit(self.smm_dir, [], self.cwd)
        self.assertEqual(result, [])

    def test_events_kwarg_skips_disk_read(self):
        """events= provided filters from given events, no disk read."""
        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        events = _common.read_events_raw(self.smm_dir)
        with patch("commits._common.read_events_raw") as mock_read:
            result = commits.open_issues_matching_commit(
                self.smm_dir,
                ["scripts/auth.py"],
                self.cwd,
                events=events,
            )
        mock_read.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])

    def test_resolutions_kwarg_skips_recompute(self):
        """Both events= and resolutions= skips compute_resolutions."""
        import resolution

        concern = make_event(
            EVENT_TYPE_CONCERN, content="auth bug", files=["scripts/auth.py"]
        )
        _common.append_safe(self.smm_dir, concern)
        events = _common.read_events_raw(self.smm_dir)
        resolutions = resolution.compute_resolutions(events)
        with patch("commits.resolution.compute_resolutions") as mock_compute:
            result = commits.open_issues_matching_commit(
                self.smm_dir,
                ["scripts/auth.py"],
                self.cwd,
                events=events,
                resolutions=resolutions,
            )
        mock_compute.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])


if __name__ == "__main__":
    unittest.main()
