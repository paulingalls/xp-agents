#!/usr/bin/env python3
"""Tests for pre_tool_bash.py: commit-time staged-lint gate (Python/ruff path).

Split from test_pre_tool_bash.py -- keeps the Python-specific staged-lint
gate tests separate from the any-language staged-lint tests.
"""

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import lint_check
import pre_tool_bash
import security_patterns  # noqa: F401 - shim import: fail loudly if module renamed
import security_scanner  # noqa: F401 - shim import: fail loudly if module renamed
from conftest import (
    _HookTestCase,
    _make_bash_input,
)


def _git_init_and_stage_all(repo: Path) -> None:
    """Make `repo` a git repo and stage every file in it.

    The staged-lint gate lints the git INDEX, so fixtures must actually stage
    the paths `get_staged_files` names — a mocked git-root over a fake tmpdir
    has no index to read.
    """
    for argv in (["git", "init", "-q"], ["git", "add", "-A"]):
        subprocess.run(argv, cwd=str(repo), check=True, capture_output=True)


class TestStagedRuffGate(_HookTestCase):
    """The commit-time lint gate: unresolved lint blocks the commit.

    story-005 replaced story-007's code-filtered gate. The old gate read a
    ``{path: codes}`` map out of the linter's text and blocked only on the two
    deferred codes (F401/F811); everything else at commit time was advisory.
    The new gate asks the linter one question — did you find anything? — and
    answers it from the EXIT CODE, then reports the linter's own output
    verbatim. Deciding *what* a finding means would take a per-language parser,
    which the cross-language guardrail forbids.

    SUPERSEDES the story-007 pins in this class: E302 (and every other
    non-deferred code) now blocks too. Customer-approved: "unresolved lint
    blocks the commit" is the uniform rule across every language, and Python
    does not get an exemption from the rule it is the template for.
    """

    _CLEAN_DIFF = (
        "diff --git a/src/app.py b/src/app.py\n"
        "--- a/src/app.py\n"
        "+++ b/src/app.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )

    def setUp(self):
        """Anchor the gate to a REAL git tree with the fixture files STAGED.

        The gate lints the git INDEX (the bytes the commit carries), not the
        working tree — so the paths `get_staged_files` names must actually be in
        the index, and `git diff --cached --name-only` names them relative to the
        repo ROOT, not the hook's cwd. A fake tmpdir would have no index to read,
        so the tree is a real repo here and its files are `git add`-ed.
        """
        super().setUp()
        self.repo = Path(tempfile.mkdtemp())
        # ruff.toml is what makes this repo a PYTHON project as far as the gate
        # is concerned. The gate detects the linter from the ecosystem's config
        # file (M4) rather than assuming ruff, so without this the staged .py
        # files would route to no linter at all and skip.
        (self.repo / "ruff.toml").touch()
        (self.repo / "src").mkdir()
        (self.repo / "src" / "app.py").write_text("x = 1\n")
        (self.repo / "src" / "a.py").write_text("x = 1\n")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "README.md").write_text("# hi\n")
        (self.repo / "config.yml").write_text("k: v\n")
        _git_init_and_stage_all(self.repo)
        self._git_root_patch = patch(
            "worktree.resolve_git_root", return_value=str(self.repo)
        )
        self._git_root_patch.start()

    def tearDown(self):
        self._git_root_patch.stop()
        shutil.rmtree(self.repo, ignore_errors=True)
        super().tearDown()

    def _commit_input(self, cwd: str | None = None) -> dict:
        return _make_bash_input(
            command="git commit -m 'fix\n\nResolves-Event: none'",
            cwd=cwd or str(self.repo),
        )

    @staticmethod
    def _findings(output: str) -> lint_check.LintRun:
        return lint_check.LintRun("findings", output)

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_staged_py_with_F401_blocks_commit(self, mock_batch, _files, _diff):
        """A staged .py file with an unused import blocks the commit, and the
        block shows what ruff actually said."""
        mock_batch.return_value = self._findings(
            "src/app.py:1:1: F401 [*] `os` imported but unused"
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("F401", msg)
        self.assertIn("src/app.py", msg)
        # One fork covers all staged files.
        mock_batch.assert_called_once()

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_staged_py_with_F811_blocks_commit(self, mock_batch, _files, _diff):
        """A staged .py file with F811 (redefinition-of-unused) blocks at commit."""
        mock_batch.return_value = self._findings(
            "src/app.py:5:1: F811 redefinition of unused `foo`"
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("F811", str(ctx.exception))

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("lint_check.run_linter_batch", return_value=lint_check.LintRun("clean", ""))
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    def test_clean_staged_py_does_not_block(self, _files, _batch, _diff):
        """A clean linter run does not block. Guards the direction that, got
        wrong, refuses every green commit in the repo."""
        try:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        except _common.BlockedError as e:
            self.fail(f"Clean staged file should not block; got: {e}")

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["docs/README.md", "config.yml"])
    @patch("lint_check.run_linter_batch")
    def test_non_python_staged_files_skip_ruff(self, mock_batch, _files, _diff):
        """Non-.py staged files must not invoke ruff (would error on bad input).

        M4 broadens this: those files will route to THEIR ecosystem's linter
        instead of being dropped. What stays true either way is that ruff is
        never handed a path it cannot read.
        """
        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        mock_batch.assert_not_called()

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_e302_now_blocks_under_the_uniform_rule(self, mock_batch, _files, _diff):
        """REVERSES story-007's `test_non_deferred_codes_do_not_block_commit`.

        Under story-007, E302 raised a never-blocking edit-time concern and the
        commit gate ignored it, so an agent could ship it by declining to act on
        the advisory. Under the uniform rule the gate blocks on any unresolved
        lint finding — and a gate that can only recognize F401/F811 is a gate
        that only works on Python, which is the whole bug this story closes.
        """
        mock_batch.return_value = self._findings(
            "src/app.py:3:5: E302 expected 2 blank lines, found 1"
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        self.assertIn("E302", str(ctx.exception))

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch")
    def test_block_reports_every_finding_not_a_filtered_subset(
        self, mock_batch, _files, _diff
    ):
        """REVERSES `test_mixed_codes_block_only_on_deferred`, which pinned the
        gate to name F401 and hide E302. Filtering the report to a code
        allowlist is the same per-language interpretation the gate no longer
        does — the human gets the linter's whole output."""
        mock_batch.return_value = self._findings(
            "src/app.py:1:1: F401 [*] `os` imported but unused\n"
            "src/app.py:3:5: E302 expected 2 blank lines, found 1"
        )
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn("F401", msg)
        self.assertIn("E302", msg)

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/a.py", "docs/README.md"])
    @patch("lint_check.run_linter_batch", return_value=lint_check.LintRun("clean", ""))
    def test_only_py_files_passed_to_ruff(self, mock_batch, _files, _diff):
        """When mixing .py and non-.py, only the .py path reaches ruff.

        The path is the materialized STAGED blob — the EXACT basename `a.py` in a
        temp subdir under `src/` (src/<tmpXXXX>/a.py), so filename-keyed rules
        match — so assert the shape, not the literal temp segment.
        """
        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        mock_batch.assert_called_once()
        args, kwargs = mock_batch.call_args
        paths = args[1] if len(args) > 1 else kwargs.get("paths")
        self.assertEqual(len(paths), 1, "only the one .py file")
        self.assertTrue(
            paths[0].startswith("src/") and paths[0].endswith("/a.py"),
            f"the staged .py blob in its temp subdir, got {paths[0]!r}",
        )

    # --- only paths that are actually THERE reach the linter ---

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/gone.py"])
    @patch("lint_check.run_linter_batch")
    def test_staged_deletion_does_not_block_the_commit(self, mock_batch, _files, _diff):
        """A commit that DELETES a .py file must not be blocked by the gate.

        `--name-only` still names a deleted path, but the file is gone from
        disk. Hand that path to a linter and it reports a read error and exits
        NON-ZERO (ruff: `E902 No such file or directory`) — which the new
        exit-code contract reads as FINDINGS, blocking the deletion commit with
        a finding no one can fix (you cannot fix a lint error in a file you are
        deleting, and 'unstage the file' means never deleting it at all).

        The old parser survived this by accident: it pre-filled every path to
        [] and E902 was not in the F401/F811 allowlist, so the error was
        silently dropped. Exit-code classification removes that accident, so
        the gate must not hand the linter a path that is not there.
        """
        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        mock_batch.assert_not_called()

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/gone.py", "src/app.py"])
    @patch("lint_check.run_linter_batch", return_value=lint_check.LintRun("clean", ""))
    def test_deletion_alongside_a_live_file_still_lints_the_live_one(
        self, mock_batch, _files, _diff
    ):
        """Dropping the deleted path must not drop the surviving one with it —
        that would be a fail-open on the file the commit actually changes."""
        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        mock_batch.assert_called_once()
        args, kwargs = mock_batch.call_args
        paths = args[1] if len(args) > 1 else kwargs.get("paths")
        self.assertEqual(len(paths), 1, "deleted path dropped, live one kept")
        # The materialized staged blob keeps its EXACT basename in a temp subdir
        # under src/ (src/<tmpXXXX>/app.py), so filename-keyed linter rules match.
        self.assertTrue(
            paths[0].startswith("src/") and paths[0].endswith("/app.py"),
            f"the surviving file's staged blob, got {paths[0]!r}",
        )

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch("lint_check.run_linter_batch", return_value=lint_check.LintRun("clean", ""))
    def test_paths_resolve_against_the_repo_root_not_the_hook_cwd(
        self, mock_batch, _files, _diff
    ):
        """git names staged paths relative to the REPO ROOT. Committing from a
        subdirectory must still lint them: resolve against the root, not the
        subdir. Otherwise every path reads as missing from the subdir, the linter
        errors out non-zero, and the gate blocks a clean commit.

        The linter runs from the CONFIG file's directory (here: ruff.toml at the
        repo root), which is the same convention the edit-time path uses so a
        monorepo's `npx eslint` resolves its local binary and flat config. That
        dir arrives realpath'd — detect_linter_config resolves it — so compare
        against the realpath, as test_lint does.
        """
        subdir = self.repo / "src"
        with contextlib.suppress(_common.BlockedError):
            pre_tool_bash.run(self._commit_input(cwd=str(subdir)), smm_dir=self.smm_dir)
        mock_batch.assert_called_once()
        args, kwargs = mock_batch.call_args
        paths = args[1] if len(args) > 1 else kwargs.get("paths")
        # The materialized staged blob, still resolved against the repo root
        # (src/…), not the subdir the commit ran from. The exact basename app.py
        # is preserved in a temp subdir (src/<tmpXXXX>/app.py).
        self.assertEqual(len(paths), 1)
        self.assertTrue(
            paths[0].startswith("src/") and paths[0].endswith("/app.py"),
            f"resolved against the root, got {paths[0]!r}",
        )
        self.assertEqual(kwargs.get("cwd"), os.path.realpath(str(self.repo)))

    # --- fail-closed on a bad read ---

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["src/app.py"])
    @patch(
        "lint_check.run_linter_batch",
        return_value=lint_check.LintRun("unverified", "ruff: `ruff` not on PATH"),
    )
    def test_unverified_run_fails_closed(self, _batch, _files, _diff):
        """A configured linter the gate could not actually run (binary missing,
        timeout, or a non-zero exit with nothing to say) must BLOCK. "We could
        not check" is not "we checked and it was clean" — SMM constraint: gates
        fail CLOSED on a bad read. Subsumes story-007's empty-batch and
        partial-coverage pins, which were two spellings of this one state."""
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        msg = str(ctx.exception).lower()
        self.assertIn("ruff", msg)

    @patch("commits.get_staged_diff", return_value=_CLEAN_DIFF)
    @patch("commits.get_staged_files", return_value=["docs/README.md"])
    @patch("lint_check.run_linter_batch")
    def test_no_py_paths_does_not_fail_closed(self, mock_batch, _files, _diff):
        """No .py files staged → no ruff call, no fail-closed. Nothing to lint
        is not a bad read."""
        try:
            pre_tool_bash.run(self._commit_input(), smm_dir=self.smm_dir)
        except _common.BlockedError as e:
            self.fail(f"No-py-paths case must not block; got: {e}")
        mock_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
