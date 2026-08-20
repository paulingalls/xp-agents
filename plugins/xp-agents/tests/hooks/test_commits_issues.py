#!/usr/bin/env python3
"""Tests for scripts/commits.py: code file review, uncommitted files, auto-link.

Split from test_commits.py -- issue-matching and file-listing helpers.
"""

import subprocess
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
    EVENT_TYPE_COMMIT,
    EVENT_TYPE_CONCERN,
    EVENT_TYPE_DEBT,
    EVENT_TYPE_DECISION,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)

_SUBPROCESS = "commits.subprocess.run"
_WATERMARK_ID = "test-commits-issues"
_SCRIPTS = Path(__file__).parent.parent.parent / "scripts"

# ---------------------------------------------------------------------------
# _run_git's three-valued result
# ---------------------------------------------------------------------------


class TestRunGitStrict(unittest.TestCase):
    """AC3, proved rather than audited: the widened result reaches only the
    one caller that asked for it.

    `_run_git` collapsed every failure into `None`, so a caller could not tell
    a read that TIMED OUT — retryable — from git running and refusing. Widening
    that for one caller must not move any of the other seventeen call sites,
    and `TestGetCodeFilesForReview`'s `test_git_failure_returns_empty` and
    `test_exception_returns_empty` below are the unchanged-behaviour half of the
    same claim: they drive the default path and must stay green untouched.
    """

    @patch(_SUBPROCESS, side_effect=subprocess.TimeoutExpired("git", 5))
    def test_a_timeout_still_declines_by_default(self, _mock):
        """The byte-for-byte old behaviour, which is what makes every existing
        call site safe without being edited."""
        self.assertIsNone(commits._run_git(["git", "status"], "/tmp"))

    @patch(_SUBPROCESS, side_effect=subprocess.TimeoutExpired("git", 5))
    def test_a_timeout_raises_only_when_asked(self, _mock):
        with self.assertRaises(commits.GitUnavailable):
            commits._run_git(["git", "status"], "/tmp", strict=True)

    @patch(_SUBPROCESS, side_effect=FileNotFoundError("no git on PATH"))
    def test_a_missing_binary_declines_even_when_asked(self, _mock):
        """`FileNotFoundError` is an `OSError`, and it is PERMANENT. Routed to
        the retryable path it would leave a git-less checkout never advancing
        and re-forking the same read on every call, forever."""
        self.assertIsNone(commits._run_git(["git", "status"], "/tmp", strict=True))

    @patch(_SUBPROCESS)
    def test_a_non_zero_exit_declines_even_when_asked(self, mock_run):
        """git RAN and refused — a bad revision, and no retry changes it."""
        mock_run.return_value = SimpleNamespace(returncode=128, stdout="")
        self.assertIsNone(commits._run_git(["git", "status"], "/tmp", strict=True))

    def test_exactly_one_call_site_asks_for_it(self):
        """The audit AC3 would otherwise need a human to redo on every change.
        A second opt-in is not forbidden — it is a decision, and this row is
        where it gets made rather than arriving unnoticed inside a diff."""
        askers = [
            f.name
            for f in sorted(_SCRIPTS.glob("*.py"))
            for line in f.read_text().splitlines()
            if "strict=True" in line
        ]
        self.assertEqual(askers, ["merged_range.py"])


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
                r.stdout = "src/a.py\0src/b.py\0"
            elif ".." in cmd[-1]:
                r.stdout = "src/b.py\0src/c.py\0"
            return r

        mock_run.side_effect = side_effect
        result = commits.get_code_files_for_review("/tmp", "abc123")
        # a.py, b.py (dedup), c.py = 3 code files
        self.assertEqual(sorted(result), ["src/a.py", "src/b.py", "src/c.py"])

    @patch(_SUBPROCESS)
    def test_filters_non_code_files(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "src/app.py\0README.md\0package.json\0"
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
            elif "--diff-filter=D" in cmd:
                # The ghost probe: paths in the index but gone from the working
                # tree. A subset of the unstaged listing below, and empty here —
                # nothing was deleted. Answering it with that listing instead
                # would call every unstaged CHANGE a deletion.
                r.stdout = ""
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        with patch("commits_issues._common.load_events_with_resolutions") as mock_read:
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
        events = _common.read_events_locked(self.smm_dir, _WATERMARK_ID)
        resolutions = resolution.compute_resolutions(events)
        with patch("commits_issues.resolution.compute_resolutions") as mock_compute:
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


_T0 = "2026-03-12T00:00:00+00:00"
_T1 = "2026-03-12T01:00:00+00:00"
_BEFORE = "2026-03-11T00:00:00+00:00"


class TestFindAddressingCommits(unittest.TestCase):
    """find_addressing_commits unions file-overlap (triage) with explicit
    commit-body id citations (extract_implicit_event_ids) — the superset
    feeding the soft MAYBE ADDRESSED nudge."""

    def _concern(self, **kw):
        return make_event(EVENT_TYPE_CONCERN, ts=_T0, **kw)

    def _commit(self, **kw):
        kw.setdefault("ts", _T1)
        return make_event(EVENT_TYPE_COMMIT, **kw)

    def test_file_overlap_only(self):
        concern = self._concern(files=["scripts/auth.py"])
        commit = self._commit(content="unrelated message", files=["scripts/auth.py"])
        result = commits.find_addressing_commits(concern, [commit])
        self.assertEqual([e["id"] for e in result], [commit["id"]])

    def test_id_citation_without_file_overlap(self):
        concern = self._concern(files=["scripts/auth.py"])
        commit = self._commit(
            content=f"fix landed elsewhere, closes {concern['id']}",
            files=["scripts/other.py"],
        )
        result = commits.find_addressing_commits(concern, [commit])
        self.assertEqual([e["id"] for e in result], [commit["id"]])

    def test_id_citation_for_fileless_concern(self):
        """A concern with no files is invisible to file-overlap, but an
        explicit id citation still surfaces the addressing commit."""
        concern = self._concern()  # no files
        commit = self._commit(
            content=f"addresses {concern['id']}", files=["scripts/x.py"]
        )
        result = commits.find_addressing_commits(concern, [commit])
        self.assertEqual([e["id"] for e in result], [commit["id"]])

    def test_both_signals_deduped(self):
        concern = self._concern(files=["scripts/auth.py"])
        commit = self._commit(
            content=f"fixes {concern['id']}", files=["scripts/auth.py"]
        )
        result = commits.find_addressing_commits(concern, [commit])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], commit["id"])

    def test_commit_before_concern_excluded(self):
        concern = self._concern(files=["scripts/auth.py"])
        commit = self._commit(
            content=f"prior work {concern['id']}",
            files=["scripts/auth.py"],
            ts=_BEFORE,
        )
        result = commits.find_addressing_commits(concern, [commit])
        self.assertEqual(result, [])

    def test_no_signal_excluded(self):
        concern = self._concern(files=["scripts/auth.py"])
        commit = self._commit(content="unrelated", files=["scripts/other.py"])
        result = commits.find_addressing_commits(concern, [commit])
        self.assertEqual(result, [])

    def test_non_commit_events_ignored(self):
        concern = self._concern(files=["scripts/auth.py"])
        status = make_event(EVENT_TYPE_STATUS, ts=_T1, content=f"touch {concern['id']}")
        result = commits.find_addressing_commits(concern, [status])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
