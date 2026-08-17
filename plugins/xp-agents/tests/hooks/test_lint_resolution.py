#!/usr/bin/env python3
"""Tests for lint_resolution.py: the commit-time and sweep resolution legs.

Split from test_auto_resolve.py (which crossed the 500-line cap) — that file
keeps the edit-time auto-resolve tests (bash_post_tool / lint_check.run()),
this one keeps everything that drives lint_resolution.py directly plus the
concerns.lint_concern_matches matcher all of it depends on.
"""

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

import concerns
import lint_check
import lint_resolution
import worktree
from conftest import _HookTestCase, _LintTmpDirMixin, make_event
from event_schema import EVENT_TYPE_CONCERN


class TestResolveLintFromConfigDir(_HookTestCase):
    """The resolution leg (lint_resolution) must run the linter from the
    config file's directory — symmetric with lint_check.run() — so a monorepo
    lint concern can actually clear after a fix. Running from git root means
    `npx eslint` is not found, run_linter returns a spurious error, and the
    concern is never resolved."""

    def test_check_and_resolve_runs_linter_from_config_dir(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        subpkg = repo / "apps" / "mobile"
        (subpkg / "src").mkdir(parents=True)
        (subpkg / "eslint.config.mjs").touch()
        target = subpkg / "src" / "foo.ts"
        target.write_text("const x = 1\n")
        normalized = worktree.normalize_path(str(target), str(repo))

        captured: dict[str, str | None] = {}

        def fake_run_linter(_linter_name, file_path, cwd=None, *, root=None, **_kw):
            captured["cwd"] = cwd
            captured["file_path"] = file_path
            # config_path is threaded now: without it a checkstyle concern raised at
            # edit time could never be cleared here (a different config would judge
            # the file by different rules).
            captured["config_path"] = _kw.get("config_path")
            return None  # clean

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.run_linter", side_effect=fake_run_linter),
        ):
            lint_resolution.check_and_resolve_lint(
                self.smm_dir,
                str(repo),
                str(repo),
                "lint-check",
                normalized,
                "Lint concern resolved on commit",
                None,
                None,
            )
        self.assertEqual(captured["cwd"], os.path.realpath(str(subpkg)))
        self.assertEqual(captured["file_path"], "src/foo.ts")

    def test_batch_path_also_runs_from_config_dir(self):
        """Same monorepo property, pinned on the BATCH leg too: resolve_lint_on_commit
        must invoke run_linter_batch from the config file's directory, or a
        monorepo lint concern could never clear once resolution batches."""
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        subpkg = repo / "apps" / "mobile"
        (subpkg / "src").mkdir(parents=True)
        (subpkg / "eslint.config.mjs").touch()
        target = subpkg / "src" / "foo.ts"
        target.write_text("const x = 1\n")
        normalized = worktree.normalize_path(str(target), str(repo))

        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {normalized}:\nno-unused-vars",
            severity="medium",
        )
        self._write_events([concern])
        events = self._read_events()

        captured: dict[str, str | None] = {}

        def fake_run_linter_batch(
            _linter_name, _paths, cwd=None, *, config_path=None, **_kw
        ):
            captured["cwd"] = cwd
            captured["config_path"] = config_path
            return lint_check.LintRun("clean", "")

        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/npx"),
            patch("lint_check.run_linter_batch", side_effect=fake_run_linter_batch),
        ):
            lint_resolution.resolve_lint_on_commit(
                self.smm_dir,
                str(repo),
                "main",
                [str(target)],
                events=events,
                resolutions=None,
            )
        self.assertEqual(captured["cwd"], os.path.realpath(str(subpkg)))
        resolutions = [
            e for e in self._read_events() if e.get("metadata", {}).get("resolves")
        ]
        self.assertEqual(len(resolutions), 1)
        self.assertIn(concern["id"], resolutions[0]["metadata"]["resolves"])


class TestPathsResolveAgainstTheRepoRoot(_HookTestCase):
    """git names committed paths relative to the REPO ROOT, so resolution has
    to normalize them there — not against the hook's cwd, which is a
    subdirectory whenever the agent committed with `git -C sub` or `cd sub &&`.

    `staged_lint` states this rule and follows it; this leg computed `git_root`
    and then normalized against `cwd` anyway. The prefix doubles
    (`pkg/src/a.py` -> `pkg/pkg/src/a.py`), the doubled path matches no recorded
    concern, the file is dropped by the has-a-concern filter, and its concern
    never clears. Silently — nothing errors, the linter simply never runs for it.

    The same file already assumed root-relative one branch over: the orphan
    sweep's `.exists()` check joins against `git_root`.
    """

    def _repo_with_concern(self):
        repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        pkg = repo / "pkg"
        (pkg / "src").mkdir(parents=True)
        (pkg / "ruff.toml").write_text("line-length = 88\n")
        (pkg / "src" / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True)
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content="Lint errors in pkg/src/a.py:\nE302 expected 2 blank lines",
            severity="medium",
        )
        self._write_events([concern])
        return repo, concern

    def _resolve_from(self, repo, cwd):
        """Drive the commit leg with git's own repo-root-relative path list."""
        with (
            patch("lint_check.shutil.which", return_value="/usr/bin/ruff"),
            patch(
                "lint_check.run_linter_batch",
                return_value=lint_check.LintRun("clean", ""),
            ),
        ):
            lint_resolution.resolve_lint_on_commit(
                self.smm_dir, str(cwd), "main", ["pkg/src/a.py"]
            )
        return [
            e for e in self._read_events() if (e.get("metadata") or {}).get("resolves")
        ]

    def test_a_commit_from_the_repo_root_resolves(self):
        """Control. Without it, the subdirectory case below could be red for a
        reason that has nothing to do with the normalization base."""
        repo, concern = self._repo_with_concern()
        resolutions = self._resolve_from(repo, repo)
        self.assertEqual(len(resolutions), 1, f"expected one resolution: {resolutions}")
        self.assertIn(concern["id"], resolutions[0]["metadata"]["resolves"])

    def test_a_commit_from_a_subdirectory_resolves_too(self):
        """The defect. `git -C pkg commit` hands the hook cwd=<repo>/pkg while
        git still names the file `pkg/src/a.py`."""
        repo, concern = self._repo_with_concern()
        resolutions = self._resolve_from(repo, repo / "pkg")
        self.assertEqual(
            len(resolutions),
            1,
            "a commit made from a subdirectory cleared no lint concern — the "
            f"committed path was normalized against cwd, not the repo root: "
            f"{resolutions}",
        )
        self.assertIn(concern["id"], resolutions[0]["metadata"]["resolves"])


class TestResolutionsThreading(_LintTmpDirMixin, _HookTestCase):
    """Verify resolve_lint_on_commit threads resolutions without re-computation."""

    def test_precomputed_resolutions_skip_recomputation(self):
        """When resolutions kwarg is provided, compute_resolutions is not called."""
        import lint_resolution
        import resolution

        norm = worktree.normalize_path("src/app.py", str(self._lint_tmpdir))
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
        )
        self._write_events([concern])

        events = self._read_events()
        precomputed = resolution.compute_resolutions(events)

        with (
            patch(
                "lint_check.detect_linter_config",
                return_value=("ruff", ""),
            ),
            patch("lint_check.run_linter", return_value=None),
            patch(
                "lint_check.run_linter_batch",
                return_value=lint_check.LintRun("clean", ""),
            ),
            patch(
                "resolution.compute_resolutions",
                wraps=resolution.compute_resolutions,
            ) as mock_compute,
        ):
            lint_resolution.resolve_lint_on_commit(
                self.smm_dir,
                str(self._lint_tmpdir),
                "main",
                ["src/app.py"],
                events=events,
                resolutions=precomputed,
            )
            mock_compute.assert_not_called()


class TestLintConcernMatches(unittest.TestCase):
    """Test lint concern matching across absolute/relative path formats."""

    def test_matches_relative_path(self):
        content = "Lint errors in src/app.py:\nE302"
        self.assertTrue(concerns.lint_concern_matches(content, "src/app.py"))

    def test_matches_absolute_path_with_relative(self):
        content = "Lint errors in /Users/paul/project/src/app.py:\nE302"
        self.assertTrue(concerns.lint_concern_matches(content, "src/app.py"))

    def test_no_match_different_file(self):
        content = "Lint errors in src/other.py:\nE302"
        self.assertFalse(concerns.lint_concern_matches(content, "src/app.py"))

    def test_no_false_positive_suffix(self):
        """old_app.py should not match app.py."""
        content = "Lint errors in src/old_app.py:\nE302"
        self.assertFalse(concerns.lint_concern_matches(content, "src/app.py"))

    def test_non_lint_concern(self):
        content = "Some other concern about src/app.py"
        self.assertFalse(concerns.lint_concern_matches(content, "src/app.py"))


class TestSweepOrphanLintConcerns(_LintTmpDirMixin, _HookTestCase):
    """Sweep unresolved lint concerns whose file isn't in this commit.

    Catches side-effect fixes (`ruff check --fix` from Bash, pre-commit
    reformatting, cross-file fixes) that don't show up as direct edits
    to the offending file. Closes debt 3863cb520147 mechanically.
    """

    def _seed_concern(self, rel_path: str) -> dict:
        # Create the file before normalizing so path realpath is stable
        # (macOS /var/folders → /private/var/folders symlink would otherwise
        # give different normalization before vs. after file creation).
        target = Path(self._lint_tmpdir) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
        norm = worktree.normalize_path(rel_path, str(self._lint_tmpdir))
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302 expected 2 blank lines",
            severity="medium",
            files=[norm],
        )
        self._write_events([concern])
        return concern

    def _run_sweep(self, committed_files, lint_clean=True):
        import lint_resolution

        events = self._read_events()
        batch_run = (
            lint_check.LintRun("clean", "")
            if lint_clean
            else lint_check.LintRun("findings", "E302")
        )
        with (
            patch(
                "lint_check.detect_linter_config",
                return_value=("ruff", str(self._lint_tmpdir / "ruff.toml")),
            ),
            patch(
                "lint_check.run_linter",
                return_value=None if lint_clean else "E302",
            ),
            patch("lint_check.run_linter_batch", return_value=batch_run),
        ):
            lint_resolution.sweep_orphan_lint_concerns(
                self.smm_dir,
                str(self._lint_tmpdir),
                "main",
                committed_files,
                events=events,
                resolutions=None,
            )

    def test_resolves_concern_for_clean_file_outside_commit(self):
        """Concern on src/other.py (not in commit), file now lints clean -> resolved."""
        concern = self._seed_concern("src/other.py")
        self._run_sweep(committed_files=["src/app.py"], lint_clean=True)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 1)
        self.assertIn(concern["id"], resolutions[0]["metadata"]["resolves"])
        self.assertEqual(resolutions[0]["metadata"].get("action"), "lint_resolved")

    def test_skips_files_already_in_commit(self):
        """Concern on src/app.py which IS in committed_files -> sweep skips
        (already handled by _resolve_lint_on_commit, no double-resolve)."""
        self._seed_concern("src/app.py")
        self._run_sweep(committed_files=["src/app.py"], lint_clean=True)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_leaves_dirty_file_concern_open(self):
        """Concern on src/other.py, file still dirty -> NOT resolved."""
        self._seed_concern("src/other.py")
        self._run_sweep(committed_files=[], lint_clean=False)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_skips_deleted_file(self):
        """Concern on a file that no longer exists -> skip, don't crash."""
        norm = worktree.normalize_path("src/gone.py", str(self._lint_tmpdir))
        concern = make_event(
            EVENT_TYPE_CONCERN,
            content=f"Lint errors in {norm}:\nE302",
            severity="medium",
            files=[norm],
        )
        self._write_events([concern])
        # File was never created — Path.exists() is False
        self._run_sweep(committed_files=[], lint_clean=True)
        events = self._read_events()
        resolutions = [e for e in events if e.get("metadata", {}).get("resolves")]
        self.assertEqual(len(resolutions), 0)

    def test_no_op_with_no_unresolved_concerns(self):
        """No unresolved lint concerns -> no work, no events written."""
        self._run_sweep(committed_files=["src/app.py"], lint_clean=True)
        events = self._read_events()
        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()
