#!/usr/bin/env python3
"""Tests for scripts/commits.py: git subprocess helpers (staged/committed
file lists, diffs, hashes, and commit/merge message bodies).

Split from test_commits.py -- these are the functions that shell out to git
(directly or via a mocked subprocess.run) rather than parse a message string.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import commits
import merged_range

# ---------------------------------------------------------------------------
# get_committed_files
# ---------------------------------------------------------------------------

_SUBPROCESS = "commits.subprocess.run"


class TestGetCommittedFiles(unittest.TestCase):
    """Test file list retrieval from last commit."""

    @patch(_SUBPROCESS)
    def test_returns_file_list(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "src/a.py\0src/b.py\0"
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
        # NUL-separated and NUL-terminated: what `--name-only -z` emits. The
        # real-git class below is what keeps this mock honest about that.
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "src/a.py\0tests/test_a.py\0README.md\0"
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


class TestGetStagedFilesAgainstRealGit(unittest.TestCase):
    """The paths git hands BACK, read from git rather than from a mock.

    Every other test in this class mocks stdout, so all of them agree with
    each other about a format none of them got from git. git C-quotes any
    path with non-ASCII bytes in its default output -- `café.js` comes back
    as the 12-character string `"caf\\303\\251.js"`, QUOTES INCLUDED -- and a
    mock spelling `café.js` can never show that.

    It is not cosmetic. Downstream, `staged_lint.path_in_index` probes
    `git cat-file -e :<path>` with whatever this returns; the quoted form
    resolves to nothing, exits non-zero, and the file is dropped from the
    lint groups entirely. A staged file with violations then commits
    UNLINTED -- silently, because "not in the index" is indistinguishable
    from a staged deletion, which is a legitimate skip.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        for args in (
            ["init", "-q"],
            ["config", "user.email", "t@example.com"],
            ["config", "user.name", "Tester"],
        ):
            subprocess.run(
                ["git", *args], cwd=self.repo, check=True, capture_output=True
            )

    def _stage(self, name: str) -> None:
        (self.repo / name).write_text("x = 1\n")
        subprocess.run(
            ["git", "add", name], cwd=self.repo, check=True, capture_output=True
        )

    def test_a_non_ascii_path_comes_back_usable(self):
        self._stage("café.js")

        self.assertEqual(commits.get_staged_files(str(self.repo)), ["café.js"])

    def test_the_returned_path_actually_resolves_in_the_index(self):
        """The property that matters downstream, asserted end to end rather
        than by string shape: whatever comes back must name a real blob."""
        self._stage("café.js")

        for path in commits.get_staged_files(str(self.repo)):
            probe = subprocess.run(
                ["git", "cat-file", "-e", f":{path}"],
                cwd=self.repo,
                capture_output=True,
            )
            self.assertEqual(
                probe.returncode, 0, f"{path!r} does not resolve in the index"
            )

    def test_ordinary_paths_are_unaffected(self):
        self._stage("plain.py")
        self._stage("dir_b.py")

        self.assertEqual(
            commits.get_staged_files(str(self.repo)), ["dir_b.py", "plain.py"]
        )

    def test_a_path_with_a_space_survives(self):
        """Spaces are why the separator must be NUL and not whitespace."""
        self._stage("my file.py")

        self.assertEqual(commits.get_staged_files(str(self.repo)), ["my file.py"])


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


# ---------------------------------------------------------------------------
# merged_range_commits
# ---------------------------------------------------------------------------


class TestMergedRangeImportsOnItsOwn(unittest.TestCase):
    """`import merged_range` must work when nothing has imported `commits` yet.

    The two used to import each other — this module for `_run_git`, `commits`
    for a re-export of `merged_range_commits` — so whichever loaded first hit a
    partially-initialised module and raised ImportError. Reachable today, not
    hypothetically: `test_commit_observer_retry.py` carried a by-name `patch`
    target purely to dodge it, and a shipped hook that imported this module
    first would have exited non-zero at import, taking the gate it enforces
    silently with it.

    A SUBPROCESS, because in-process the suite has already imported both in the
    working order and cannot see the failure at all.
    """

    def test_importing_it_before_commits_succeeds(self):
        scripts = str(Path(__file__).parent.parent.parent / "scripts")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, {scripts!r}); import merged_range",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class TestMergedRangeCommits(unittest.TestCase):
    """Every merge emitter's only path to a merged-in commit's trailer. Real repo,
    real `--no-ff` merge — git plumbing a mock cannot stand in for.

    Retargeted from `merged_range_bodies`, which the third emitter's convergence
    left with no caller: all three now decide commit by commit."""

    def _git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        )
        return proc.stdout.strip()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Tester")
        self._git("config", "commit.gpgsign", "false")
        (self.repo / "seed.py").write_text("x = 1\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "seed")

    def _commit(self, name: str, content: str, message: str) -> str:
        (self.repo / name).write_text(content)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD")

    def test_returns_both_merged_commit_bodies(self):
        self._git("checkout", "-q", "-b", "feature")
        self._commit("a.py", "a = 1\n", "feat: a\n\nResolves-Event: aaaaaaaaaaaa")
        self._commit("b.py", "b = 1\n", "feat: b\n\nResolves-Event: bbbbbbbbbbbb")
        self._git("checkout", "-q", "main")
        self._git("merge", "-q", "--no-ff", "-m", "Merge feature", "feature")
        merge_hash = self._git("rev-parse", "HEAD")

        pairs = merged_range.merged_range_commits(str(self.repo), merge_hash)

        bodies = "\n".join(body for _, body in pairs)
        self.assertIn("aaaaaaaaaaaa", bodies)
        self.assertIn("bbbbbbbbbbbb", bodies)
        self.assertEqual(len(pairs), 2, f"expected both incoming commits: {pairs}")
        for landed, _ in pairs:
            self.assertNotEqual(landed, merge_hash, "the merge itself must be filtered")

    def test_non_merge_commit_yields_nothing(self):
        head = self._commit("c.py", "c = 1\n", "feat: c")
        self.assertEqual(merged_range.merged_range_commits(str(self.repo), head), [])

    def test_unknown_hash_yields_nothing(self):
        """Fails toward a MISS rather than raising into a synchronous hook."""
        self.assertEqual(
            merged_range.merged_range_commits(str(self.repo), "deadbeefcafe"), []
        )


if __name__ == "__main__":
    unittest.main()
