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
                "stdout": ("src/app.py\0README.md\0tests/test_app.py\0"),
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
# get_uncommitted_files -- the "is the tree dirty?" signal
# ---------------------------------------------------------------------------


def _git_out(stdout: str):
    return type("R", (), {"returncode": 0, "stdout": stdout})()


class TestGetUncommittedFiles(unittest.TestCase):
    """commits.get_uncommitted_files() -- wider than get_uncommitted_code_files.

    Backs the TDD gate's prior-session tree check
    (tdd_check.find_last_test_signal). Every narrowing here is a way to DISARM
    that gate, so test files and untracked files must both count as dirty.
    """

    @patch(_SUBPROCESS)
    def test_includes_test_files(self, mock_run):
        """A tree dirty with ONLY a broken test file is still dirty. The
        narrower get_uncommitted_code_files drops it and reads CLEAN."""
        mock_run.side_effect = [
            _git_out(""),
            _git_out("tests/test_app.py\n"),
            _git_out(""),
        ]
        self.assertEqual(commits.get_uncommitted_files("/tmp"), ["tests/test_app.py"])

    @patch(_SUBPROCESS)
    def test_includes_untracked_files(self, mock_run):
        """`git diff` never lists untracked files -- but a brand-new, never-added
        failing test is the most common shape of the TDD red step."""
        mock_run.side_effect = [
            _git_out(""),
            _git_out(""),
            _git_out("tests/test_new.py\0src/new_mod.py\0"),
        ]
        self.assertEqual(
            commits.get_uncommitted_files("/tmp"),
            ["src/new_mod.py", "tests/test_new.py"],
        )

    @patch(_SUBPROCESS)
    def test_excludes_non_code_and_dedups(self, mock_run):
        """Docs churn is not broken work; a file in two lists appears once."""
        mock_run.side_effect = [
            _git_out("src/app.py\0README.md\0"),
            _git_out("src/app.py\n"),
            _git_out(""),
        ]
        self.assertEqual(commits.get_uncommitted_files("/tmp"), ["src/app.py"])

    @patch(_SUBPROCESS)
    def test_empty_on_clean_tree(self, mock_run):
        mock_run.side_effect = [_git_out(""), _git_out(""), _git_out("")]
        self.assertEqual(commits.get_uncommitted_files("/tmp"), [])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_no_repo_reads_clean(self, _mock):
        """Graceful degradation. git is absent / this is not a work tree: a
        structural, permanent condition. Reads as CLEAN, so a project git
        cannot answer for at all never gates forever on a prior-session
        failure."""
        self.assertEqual(commits.get_uncommitted_files("/tmp"), [])

    @patch(_SUBPROCESS)
    def test_scan_timeout_in_a_real_repo_is_unanswered_not_clean(self, mock_run):
        """Anti-disarm, and the reason "no answer" is not one condition.

        The untracked scan walks the WHOLE worktree, so it is the likeliest
        _run_git timeout here. Collapsing that to "no files" reads as a CLEAN
        tree and UN-GATES a real prior-session failure. The O(1) repo probe
        still answers when the walking scan does not, which is what tells this
        apart from the no-repo case above.
        """
        mock_run.side_effect = [
            _git_out(""),  # staged
            _git_out(""),  # unstaged
            subprocess.TimeoutExpired(cmd="git ls-files", timeout=5),
            _git_out("true"),  # repo probe: yes, this really is a work tree
        ]
        self.assertIsNone(commits.get_uncommitted_files("/tmp"))


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
        with patch("commits._common.load_events_with_resolutions") as mock_read:
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
