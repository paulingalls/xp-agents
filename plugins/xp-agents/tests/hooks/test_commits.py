#!/usr/bin/env python3
"""Tests for scripts/commits.py: parse, extract, and git helpers.

Issue-matching and file-listing tests live in test_commits_issues.py.
"""

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
# extract_resolves_trailer
# ---------------------------------------------------------------------------


class TestExtractResolvesTrailer(unittest.TestCase):
    """Test extraction of Resolves-Event: trailer from commit body."""

    def test_single_id(self):
        body = "Fix the bug\n\nRationale.\n\nResolves-Event: 4eb35ddcd24e"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_comma_separated_ids(self):
        body = "Title\n\nResolves-Event: 4eb35ddcd24e, a55290ae79b9"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e", "a55290ae79b9"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_multiple_trailer_lines(self):
        body = (
            "Title\n\nbody.\n\n"
            "Resolves-Event: 4eb35ddcd24e\n"
            "Resolves-Event: a55290ae79b9"
        )
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e", "a55290ae79b9"])
        self.assertNotIn("Resolves-Event", cleaned)

    def test_case_insensitive_key(self):
        body = "Title\n\nresolves-event: 4eb35ddcd24e"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["4eb35ddcd24e"])
        self.assertNotIn("resolves-event", cleaned.lower())

    def test_deduplicates_preserving_order(self):
        body = (
            "Title\n\n"
            "Resolves-Event: abc123abc123\n"
            "Resolves-Event: def456def456, abc123abc123"
        )
        ids, *_ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, ["abc123abc123", "def456def456"])

    def test_ignores_inline_mentions(self):
        """Trailer must start at line beginning, not in prose."""
        body = "Fix the thing that Resolves-Event: 4eb35ddcd24e in passing"
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, body)

    def test_rejects_non_hex_ids(self):
        body = "Title\n\nResolves-Event: not-a-hex-id"
        ids, *_ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])

    def test_rejects_wrong_length_ids(self):
        body = "Title\n\nResolves-Event: abc123, 1234567890123456"
        ids, *_ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])

    def test_no_trailer(self):
        body = "Fix the bug\n\nSome rationale."
        ids, cleaned, _ = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, body)

    def test_empty_body(self):
        ids, cleaned, _ = commits.extract_resolves_trailer("")
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, "")

    def test_none_body(self):
        ids, cleaned, has = commits.extract_resolves_trailer(None)
        self.assertEqual(ids, [])
        self.assertEqual(cleaned, "")
        self.assertFalse(has)

    def test_has_trailer_true_with_valid_id(self):
        body = "Fix bug\n\nResolves-Event: 4eb35ddcd24e"
        _, _, has = commits.extract_resolves_trailer(body)
        self.assertTrue(has)

    def test_has_trailer_true_with_none(self):
        """Resolves-Event: none is valid discipline — trailer is present."""
        body = "Fix bug\n\nResolves-Event: none"
        ids, _, has = commits.extract_resolves_trailer(body)
        self.assertEqual(ids, [])
        self.assertTrue(has)

    def test_has_trailer_false_when_absent(self):
        body = "Fix bug\n\nSome rationale."
        _, _, has = commits.extract_resolves_trailer(body)
        self.assertFalse(has)


# ---------------------------------------------------------------------------
# extract_implicit_event_ids
# ---------------------------------------------------------------------------


class TestExtractImplicitEventIds(unittest.TestCase):
    """Test extraction of bare 12-hex event IDs from commit body."""

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
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"ffffffffffff"}),
            [],
        )

    def test_eleven_char_hex_rejected(self):
        body = "see a1b2c3d4e5f"  # 11 chars
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_thirteen_char_hex_rejected(self):
        body = "see a1b2c3d4e5f6a"  # 13 chars
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_uppercase_hex_rejected(self):
        body = "see A1B2C3D4E5F6"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_non_hex_chars_rejected(self):
        body = "see g1b2c3d4e5f6"  # 'g' is not hex
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

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
        body = "see commit a1b2c3d4e5f6deadbeef01234567890abcdef1234"
        self.assertEqual(
            commits.extract_implicit_event_ids(body, {"a1b2c3d4e5f6"}),
            [],
        )

    def test_empty_body_returns_empty(self):
        self.assertEqual(
            commits.extract_implicit_event_ids("", {"a1b2c3d4e5f6"}),
            [],
        )

    def test_none_body_returns_empty(self):
        self.assertEqual(
            commits.extract_implicit_event_ids(None, {"a1b2c3d4e5f6"}),
            [],
        )

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
# get_staged_files
# ---------------------------------------------------------------------------


class TestGetStagedFiles(unittest.TestCase):
    """Test staged file list retrieval."""

    @patch(_SUBPROCESS)
    def test_returns_staged_files(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "src/a.py\ntests/test_a.py\nREADME.md\n"
        result = commits.get_staged_files("/tmp")
        self.assertEqual(result, ["README.md", "src/a.py", "tests/test_a.py"])

    @patch(_SUBPROCESS)
    def test_failure_returns_empty(self, mock_run):
        mock_run.return_value.returncode = 1
        self.assertEqual(commits.get_staged_files("/tmp"), [])

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_empty(self, _mock):
        self.assertEqual(commits.get_staged_files("/tmp"), [])

    @patch(_SUBPROCESS)
    def test_empty_staging_returns_empty(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        self.assertEqual(commits.get_staged_files("/tmp"), [])


# ---------------------------------------------------------------------------
# get_staged_diff
# ---------------------------------------------------------------------------


class TestGetStagedDiff(unittest.TestCase):
    """Test staged unified-diff retrieval."""

    @patch(_SUBPROCESS)
    def test_returns_diff_text(self, mock_run):
        mock_run.return_value.returncode = 0
        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        mock_run.return_value.stdout = diff
        self.assertEqual(commits.get_staged_diff("/tmp"), diff.strip())

    @patch(_SUBPROCESS)
    def test_failure_returns_none(self, mock_run):
        """Non-zero exit → None so callers can fail closed (security gate)."""
        mock_run.return_value.returncode = 1
        self.assertIsNone(commits.get_staged_diff("/tmp"))

    @patch(_SUBPROCESS, side_effect=OSError("no git"))
    def test_exception_returns_none(self, _mock):
        """OSError → None so callers can fail closed (security gate)."""
        self.assertIsNone(commits.get_staged_diff("/tmp"))

    @patch(_SUBPROCESS)
    def test_empty_staging_returns_empty_string(self, mock_run):
        """Git ran successfully but no staged changes → empty string (not None)."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        self.assertEqual(commits.get_staged_diff("/tmp"), "")


# ---------------------------------------------------------------------------
# get_head_commit_hash
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# get_filenames_from_diff
# ---------------------------------------------------------------------------


class TestGetFilenamesFromDiff(unittest.TestCase):
    """Test parsing of post-image filenames from a unified diff."""

    def test_empty_string(self):
        self.assertEqual(commits.get_filenames_from_diff(""), [])

    def test_modified_file(self):
        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["src/a.py"])

    def test_added_file(self):
        """New file: --- /dev/null, +++ b/path → emit path."""
        diff = (
            "diff --git a/src/new.py b/src/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/new.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+new line\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["src/new.py"])

    def test_deleted_file(self):
        """Deleted file: --- a/path, +++ /dev/null → emit path from --- line."""
        diff = (
            "diff --git a/src/old.py b/src/old.py\n"
            "deleted file mode 100644\n"
            "--- a/src/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            "-deleted line\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["src/old.py"])

    def test_pure_rename_no_content_change(self):
        """Rename with no content change has no +++/---; uses rename to."""
        diff = (
            "diff --git a/src/old_name.py b/src/new_name.py\n"
            "similarity index 100%\n"
            "rename from src/old_name.py\n"
            "rename to src/new_name.py\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["src/new_name.py"])

    def test_rename_with_content_change(self):
        """Rename + edit: emit only the new path (matches --name-only)."""
        diff = (
            "diff --git a/src/old.py b/src/new.py\n"
            "similarity index 95%\n"
            "rename from src/old.py\n"
            "rename to src/new.py\n"
            "--- a/src/old.py\n"
            "+++ b/src/new.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["src/new.py"])

    def test_multiple_files_mixed(self):
        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-x\n"
            "+y\n"
            "diff --git a/src/b.py b/src/b.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/b.py\n"
            "@@ -0,0 +1,1 @@\n"
            "+content\n"
            "diff --git a/src/c.py b/src/c.py\n"
            "deleted file mode 100644\n"
            "--- a/src/c.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            "-bye\n"
        )
        self.assertEqual(
            commits.get_filenames_from_diff(diff),
            ["src/a.py", "src/b.py", "src/c.py"],
        )

    def test_dedupes_repeated_paths(self):
        """Same file appearing twice (shouldn't normally happen) is deduped."""
        diff = (
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-1\n"
            "+2\n"
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -2,1 +2,1 @@\n"
            "-3\n"
            "+4\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["x.py"])

    def test_path_with_spaces(self):
        diff = (
            "diff --git a/src/has space.py b/src/has space.py\n"
            "--- a/src/has space.py\n"
            "+++ b/src/has space.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["src/has space.py"])

    def test_lines_in_content_starting_with_plus_plus_plus_ignored(self):
        """A diff body line like '+++ something' inside content must not match.

        The +++ b/ marker is the file header; content additions begin with
        a single '+'. We anchor on '+++ b/' / '+++ /dev/null' to avoid
        false matches.
        """
        diff = (
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1,1 +1,3 @@\n"
            " context\n"
            "+++ this line is added content, not a header\n"
            "+more\n"
        )
        self.assertEqual(commits.get_filenames_from_diff(diff), ["x.py"])


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
        self.assertIsNotNone(result)
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


if __name__ == "__main__":
    unittest.main()
