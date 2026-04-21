#!/usr/bin/env python3
"""Tests for scripts/commits.py — shared commit utilities."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import commits
from conftest import _SMMTestCase, make_event

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
# extract_resolves_trailer
# ---------------------------------------------------------------------------


class TestExtractResolvesTrailer(unittest.TestCase):
    """Test extraction of Resolves-Event: trailer from commit body."""

    def test_single_id(self):
        body = "Fix the bug\n\nRationale.\n\nResolves-Event: 4eb35ddcd24e"
        ids, cleaned = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_comma_separated_ids(self):
        body = "Title\n\nResolves-Event: 4eb35ddcd24e, a55290ae79b9"
        ids, cleaned = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e", "a55290ae79b9"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_multiple_trailer_lines(self):
        body = (
            "Title\n\nbody.\n\n"
            "Resolves-Event: 4eb35ddcd24e\n"
            "Resolves-Event: a55290ae79b9"
        )
        ids, cleaned = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e", "a55290ae79b9"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_case_insensitive_key(self):
        body = "Title\n\nresolves-event: 4eb35ddcd24e"
        ids, cleaned = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e"])
        self.assertNotIn("resolves-event", cleaned.lower())

    def test_deduplicates_preserving_order(self):
        body = (
            "Title\n\n"
            "Resolves-Event: abc123abc123\n"
            "Resolves-Event: def456def456, abc123abc123"
        )
        ids, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["abc123abc123", "def456def456"])

    def test_ignores_inline_mentions(self):
        """Trailer must start at the beginning of a line, not in prose."""
        body = "Fix the thing that Resolves-Event: 4eb35ddcd24e in passing"
        ids, cleaned = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, body)

    def test_rejects_non_hex_ids(self):
        body = "Title\n\nResolves-Event: not-a-hex-id"
        ids, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])

    def test_rejects_wrong_length_ids(self):
        body = "Title\n\nResolves-Event: abc123, 1234567890123456"
        ids, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])

    def test_no_trailer(self):
        body = "Fix the bug\n\nSome rationale."
        ids, cleaned = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, body)

    def test_empty_body(self):
        ids, cleaned = commits.extract_resolves_trailer("")
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, "")

    def test_none_body(self):
        ids, cleaned = commits.extract_resolves_trailer(None)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, "")


# ---------------------------------------------------------------------------
# extract_implicit_event_ids
# ---------------------------------------------------------------------------


class TestExtractImplicitEventIds(unittest.TestCase):
    """Test extraction of bare 12-hex event IDs from commit body prose."""

    def test_single_bare_id_matched(self):
        body = "fixes a1b2c3d4e5f6"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            ["a1b2c3d4e5f6"],
        )

    def test_empty_known_ids_returns_empty(self):
        body = "fixes a1b2c3d4e5f6"
        self.assertEqual(commits.extract_implicit_event_ids(body, set()), [])

    def test_id_not_in_known_ids_ignored(self):
        body = "closes concern a1b2c3d4e5f6"
        self.assertEqual(commits.extract_implicit_event_ids(body, {"ffffffffffff"}), [])

    def test_eleven_char_hex_rejected(self):
        body = "see a1b2c3d4e5f"  # 11 chars
        self.assertEqual(commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}), [])

    def test_thirteen_char_hex_rejected(self):
        body = "see a1b2c3d4e5f6a"  # 13 chars — embedded, word-boundary blocks it
        self.assertEqual(commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}), [])

    def test_uppercase_hex_rejected(self):
        body = "see A1B2C3D4E5F6"
        self.assertEqual(commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}), [])

    def test_non_hex_chars_rejected(self):
        body = "see g1b2c3d4e5f6"  # 'g' is not hex
        self.assertEqual(commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}), [])

    def test_deduplicates_preserving_first_seen_order(self):
        body = "fixes a1b2c3d4e5f6 and again a1b2c3d4e5f6"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            ["a1b2c3d4e5f6"],
        )

    def test_multiple_distinct_ids_first_seen_order(self):
        body = "closes b222222222b2, then a111111111a1"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a111111111a1", "b222222222b2"}),
            ["b222222222b2", "a111111111a1"],
        )

    def test_id_embedded_in_longer_hex_not_matched(self):
        # 40-char commit hash contains a 12-char hex substring, but word
        # boundary prevents the inner slice from matching on its own.
        body = "see commit a1b2c3d4e5f6deadbeef01234567890abcdef1234"
        self.assertEqual(commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}), [])

    def test_empty_body_returns_empty(self):
        self.assertEqual(commits.extract_implicit_event_ids("", {"a1b2c3d4e5f6"}), [])

    def test_none_body_returns_empty(self):
        self.assertEqual(commits.extract_implicit_event_ids(None, {"a1b2c3d4e5f6"}), [])

    def test_punctuation_around_id_still_matches(self):
        body = "fixes (a1b2c3d4e5f6)."
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            ["a1b2c3d4e5f6"],
        )


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
# get_commit_message_body
# ---------------------------------------------------------------------------


class TestGetCommitMessageBody(unittest.TestCase):
    """Test full commit message body retrieval."""

    @patch(_SUBPROCESS)
    def test_returns_full_body(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Fix the bug\n\nDetailed explanation.\n"
        result = commits.get_commit_message_body("/tmp")
        self.assertEqual(result, "Fix the bug\n\nDetailed explanation.")

    @patch(_SUBPROCESS)
    def test_single_line_message(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Quick fix\n"
        self.assertEqual(commits.get_commit_message_body("/tmp"), "Quick fix")

    @patch(_SUBPROCESS)
    def test_failure_returns_none(self, mock_run):
        mock_run.return_value.returncode = 1
        self.assertIsNone(commits.get_commit_message_body("/tmp"))

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_none(self, _mock):
        self.assertIsNone(commits.get_commit_message_body("/tmp"))


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
            {"returncode": 0, "stdout": "src/app.py\nREADME.md\ntests/test_app.py\n"},
        )()
        unstaged = type("R", (), {"returncode": 0, "stdout": "src/utils.py\n"})()
        mock_run.side_effect = [staged, unstaged]
        result = commits.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, ["src/app.py", "src/utils.py"])

    @patch(_SUBPROCESS)
    def test_empty_on_no_changes(self, mock_run):
        """No changed files → empty list."""
        empty = type("R", (), {"returncode": 0, "stdout": ""})()
        mock_run.side_effect = [empty, empty]
        result = commits.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, [])

    @patch(_SUBPROCESS)
    def test_deduplicates_staged_and_unstaged(self, mock_run):
        """Same file in both staged and unstaged → appears once."""
        staged = type("R", (), {"returncode": 0, "stdout": "src/app.py\n"})()
        unstaged = type("R", (), {"returncode": 0, "stdout": "src/app.py\n"})()
        mock_run.side_effect = [staged, unstaged]
        result = commits.get_uncommitted_code_files("/tmp")
        self.assertEqual(result, ["src/app.py"])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_empty(self, _mock):
        """Subprocess failure → empty list (graceful degradation)."""
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
        concern = make_event("concern", content="auth bug", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, concern)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py", "README.md"], self.cwd
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])

    def test_normalizes_path_variants(self):
        concern = make_event("concern", content="auth bug", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, concern)
        # Commit diff might surface the same file as "./scripts/auth.py" or
        # an absolute path; normalize_path should canonicalize both sides.
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["./scripts/auth.py"], self.cwd
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])

    def test_excludes_resolved_concerns(self):
        concern = make_event("concern", content="auth bug", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, concern)
        decision = make_event(
            "decision",
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
        no_files = make_event("concern", content="no files")
        empty_files = make_event("concern", content="empty", files=[])
        _common.append_safe(self.smm_dir, no_files)
        _common.append_safe(self.smm_dir, empty_files)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(result, [])

    def test_includes_debt_with_file_overlap(self):
        debt = make_event("debt", content="legacy code", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, debt)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], debt["id"])

    def test_excludes_resolved_debt(self):
        debt = make_event("debt", content="legacy code", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, debt)
        resolver = make_event(
            "status", content="fixed", metadata={"resolves": [debt["id"]]}
        )
        _common.append_safe(self.smm_dir, resolver)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(result, [])

    def test_excludes_non_concern_non_debt_events(self):
        question = make_event("question", content="why?", files=["scripts/auth.py"])
        assumption = make_event(
            "assumption", content="guess", files=["scripts/auth.py"]
        )
        for ev in (question, assumption):
            _common.append_safe(self.smm_dir, ev)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["scripts/auth.py"], self.cwd
        )
        self.assertEqual(result, [])

    def test_no_overlap_returns_empty(self):
        concern = make_event("concern", content="auth bug", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, concern)
        result = commits.open_issues_matching_commit(
            self.smm_dir, ["README.md"], self.cwd
        )
        self.assertEqual(result, [])

    def test_empty_commit_files_returns_empty(self):
        concern = make_event("concern", content="auth bug", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, concern)
        result = commits.open_issues_matching_commit(self.smm_dir, [], self.cwd)
        self.assertEqual(result, [])

    def test_events_kwarg_skips_disk_read(self):
        """events= provided filters from given events, no disk read."""
        from unittest.mock import patch

        concern = make_event("concern", content="auth bug", files=["scripts/auth.py"])
        _common.append_safe(self.smm_dir, concern)
        events = _common.read_events_raw(self.smm_dir)
        with patch("commits._common.read_events_raw") as mock_read:
            result = commits.open_issues_matching_commit(
                self.smm_dir, ["scripts/auth.py"], self.cwd, events=events
            )
        mock_read.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], concern["id"])


if __name__ == "__main__":
    unittest.main()
