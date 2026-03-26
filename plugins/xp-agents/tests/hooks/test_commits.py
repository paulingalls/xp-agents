#!/usr/bin/env python3
"""Tests for scripts/commits.py — shared commit utilities."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commits

# ---------------------------------------------------------------------------
# parse_commit_message
# ---------------------------------------------------------------------------


class TestParseCommitMessage(unittest.TestCase):
    """Test commit message extraction from git output."""

    def test_standard_output(self):
        out = "[main abc1234] Fix the bug\n 1 file changed"
        self.assertEqual(commits.parse_commit_message(out), "Fix the bug")

    def test_branch_with_slash(self):
        out = "[feature/foo abc1234] Add feature"
        self.assertEqual(commits.parse_commit_message(out), "Add feature")

    def test_no_match(self):
        self.assertIsNone(commits.parse_commit_message("not a commit"))

    def test_empty(self):
        self.assertIsNone(commits.parse_commit_message(""))


# ---------------------------------------------------------------------------
# get_committed_files
# ---------------------------------------------------------------------------

_SUBPROCESS = "commits.subprocess.run"


class TestGetCommittedFiles(unittest.TestCase):
    """Test file list retrieval from last commit."""

    @patch(_SUBPROCESS)
    def test_returns_file_list(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "src/a.py\nsrc/b.py\n"
        result = commits.get_committed_files("/tmp")
        self.assertEqual(result, ["src/a.py", "src/b.py"])

    @patch(_SUBPROCESS)
    def test_failure_returns_empty(self, mock_run):
        mock_run.return_value.returncode = 1
        self.assertEqual(commits.get_committed_files("/tmp"), [])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_empty(self, _mock):
        self.assertEqual(commits.get_committed_files("/tmp"), [])


# ---------------------------------------------------------------------------
# get_head_commit_hash
# ---------------------------------------------------------------------------


class TestGetHeadCommitHash(unittest.TestCase):
    """Test HEAD commit hash retrieval."""

    @patch(_SUBPROCESS)
    def test_returns_hash(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "abc123def456\n"
        self.assertEqual(commits.get_head_commit_hash("/tmp"), "abc123def456")

    @patch(_SUBPROCESS)
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value.returncode = 1
        self.assertIsNone(commits.get_head_commit_hash("/tmp"))

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_none(self, _mock):
        self.assertIsNone(commits.get_head_commit_hash("/tmp"))


# ---------------------------------------------------------------------------
# get_code_files_for_review
# ---------------------------------------------------------------------------


class TestGetCodeFilesForReview(unittest.TestCase):
    """Test code file counting for review cycle gate."""

    @patch(_SUBPROCESS)
    def test_combines_staged_and_since_review(self, mock_run):
        def side_effect(cmd, **_kwargs):
            r = type("R", (), {"returncode": 0, "stdout": ""})()
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
            r = type("R", (), {"returncode": 0, "stdout": ""})()
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
            "/tmp", "abc123", command="git add -A && git commit -m 'test'"
        )
        self.assertIn("src/a.py", result)
        self.assertIn("src/b.py", result)


class TestReviewCycleThreshold(unittest.TestCase):
    """Test threshold constant."""

    def test_threshold_is_three(self):
        self.assertEqual(commits.REVIEW_CYCLE_THRESHOLD, 3)


if __name__ == "__main__":
    unittest.main()
