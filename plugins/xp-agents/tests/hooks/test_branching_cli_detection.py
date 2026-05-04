#!/usr/bin/env python3
"""Tests for branching CLI: pre-existing branch detection and plan-branch
prefix-fallback resolution (shared merge-target theme).
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import branching

_GIT_ENV = _bf.GIT_ENV
_init_repo = _bf.init_repo
_init_repo_in_spaced_parent = _bf.init_repo_in_spaced_parent
_write_system_context = _bf.write_system_context
_seed_sprint_with_stories = _bf.seed_sprint_with_stories


class TestRecordedPlanBranchPrefixFallback(unittest.TestCase):
    """sprint-032 C1b: _recorded_plan_branch falls back via prefix match.

    Constraints pillar: 'lookups use stored name with prefix-fallback to
    handle slug drift'. If the plan branch was renamed locally (e.g. user
    appended a -v2 suffix or shortened the slug), exact branch_exists
    misses and get_merge_target silently routes to primary. Mirror the
    pattern get_story_base_branch already uses for sprint branches.
    """

    def test_falls_back_to_prefix_match_when_exact_missing(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-feat")
            # Create a branch with a drifted slug (no exact match).
            subprocess.run(
                ["git", "checkout", "-b", "paul/plan-feat-v2"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            with patch("sys.stderr") as fake_err:
                result = branching._recorded_plan_branch(td, smm_dir)
            self.assertEqual(result, "paul/plan-feat-v2")
            # Communication: the drift fallback must be visible.
            printed = "".join(
                str(call.args[0]) for call in fake_err.write.call_args_list if call.args
            )
            self.assertIn("paul/plan-feat", printed)
            self.assertIn("paul/plan-feat-v2", printed)

    def test_anchored_glob_excludes_substring_extensions(self):
        """`<branch>-*` must not match `<branch>extra` (e.g. featured)."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-feat")
            # Substring-extension branch: 'feat' is a prefix but no -separator.
            subprocess.run(
                ["git", "checkout", "-b", "paul/plan-featured"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = branching._recorded_plan_branch(td, smm_dir)
            self.assertIsNone(result)

    def test_returns_none_when_no_prefix_match(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-missing")
            # Different prefix entirely — no match.
            subprocess.run(
                ["git", "checkout", "-b", "paul/other-branch"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = branching._recorded_plan_branch(td, smm_dir)
            self.assertIsNone(result)

    def test_exact_match_preferred_over_prefix(self):
        """When the recorded branch exists exactly, return it (no scan)."""
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _bf.seed_plan(smm_dir, branch="paul/plan-feat")
            # Create both an exact match AND a longer-prefix sibling.
            subprocess.run(
                ["git", "branch", "paul/plan-feat"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "branch", "paul/plan-feat-v2"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            result = branching._recorded_plan_branch(td, smm_dir)
            self.assertEqual(result, "paul/plan-feat")


class TestPreExistingBranchDetection(unittest.TestCase):
    """CLI reports 'created:' or 'resumed:' prefix for sprint/plan branches."""

    def _run_branching(self, smm_dir, *args):
        script = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")
        return subprocess.run(
            [sys.executable, script, "--smm-dir", str(smm_dir), *args],
            capture_output=True,
            text=True,
            env=_GIT_ENV,
        )

    def test_create_sprint_reports_created(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            r = self._run_branching(
                smm_dir,
                "create-sprint",
                "--cwd",
                td,
                "--sprint",
                "sprint-099",
                "--slug",
                "new-sprint",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                r.stdout.strip().startswith("created:"),
                f"Expected 'created:' prefix, got: {r.stdout.strip()!r}",
            )

    def test_create_sprint_reports_resumed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            subprocess.run(
                ["git", "branch", "test/sprint-099-old-sprint"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            r = self._run_branching(
                smm_dir,
                "create-sprint",
                "--cwd",
                td,
                "--sprint",
                "sprint-099",
                "--slug",
                "old-sprint",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                r.stdout.strip().startswith("resumed:"),
                f"Expected 'resumed:' prefix, got: {r.stdout.strip()!r}",
            )

    def test_create_plan_reports_created(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            r = self._run_branching(
                smm_dir,
                "create-plan",
                "--cwd",
                td,
                "--slug",
                "new-plan",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                r.stdout.strip().startswith("created:"),
                f"Expected 'created:' prefix, got: {r.stdout.strip()!r}",
            )

    def test_create_plan_reports_resumed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            subprocess.run(
                ["git", "branch", "test/plan-old-plan"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            r = self._run_branching(
                smm_dir,
                "create-plan",
                "--cwd",
                td,
                "--slug",
                "old-plan",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(
                r.stdout.strip().startswith("resumed:"),
                f"Expected 'resumed:' prefix, got: {r.stdout.strip()!r}",
            )


class TestListTeammateWorktreePathsCli(unittest.TestCase):
    """branching_cli list-teammate-worktree-paths emits ``story-id\\tabs-path``.

    Format consumed by /xp-accept's preload so the SKILL prose can `cd`
    into each story's worktree before running its acceptance command.
    Tab delimiter: worktree paths can contain spaces on macOS
    (``/Users/foo bar/...``); a single-space delimiter would require
    fragile parsing on the consumer side. Empty stdout when no live
    teammate worktrees.
    """

    def _make_worktree(self, td, story_id):
        """Create a real worktree at .claude/worktrees/worktree-<story-id>.

        Returns the realpath because git porcelain resolves /var/folders
        to /private/var/folders on macOS.
        """
        path = Path(td) / ".claude" / "worktrees" / f"worktree-{story_id}"
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", f"u/{story_id}-x", str(path), "HEAD"],
            cwd=td,
            capture_output=True,
            check=True,
        )
        return os.path.realpath(str(path))

    def _run_branching(self, smm_dir, *args):
        script = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")
        return subprocess.run(
            [sys.executable, script, "--smm-dir", str(smm_dir), *args],
            capture_output=True,
            text=True,
            env=_GIT_ENV,
        )

    def test_empty_stdout_when_no_teammates(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            r = self._run_branching(
                Path(smm), "list-teammate-worktree-paths", "--cwd", td
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "")

    def test_emits_story_id_tab_path_per_worktree(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            try:
                p1 = self._make_worktree(td, "story-001")
                p2 = self._make_worktree(td, "story-042")
                r = self._run_branching(
                    Path(smm), "list-teammate-worktree-paths", "--cwd", td
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                lines = r.stdout.strip().splitlines()
                self.assertEqual(
                    sorted(lines),
                    sorted([f"story-001\t{p1}", f"story-042\t{p2}"]),
                )
            finally:
                for name in ("worktree-story-001", "worktree-story-042"):
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", name],
                        cwd=td,
                        capture_output=True,
                    )

    def test_path_with_space_preserved_verbatim(self):
        """Worktree path containing a space round-trips verbatim under tab.

        macOS user dirs commonly contain spaces; the old space-delimited
        emit forced consumers to guess where the path ended.
        """
        with (
            tempfile.TemporaryDirectory() as parent,
            tempfile.TemporaryDirectory() as smm,
        ):
            td = _init_repo_in_spaced_parent(parent)
            try:
                p1 = self._make_worktree(td, "story-001")
                self.assertIn(" ", p1)
                r = self._run_branching(
                    Path(smm), "list-teammate-worktree-paths", "--cwd", td
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                line = r.stdout.strip()
                story_id, _, path = line.partition("\t")
                self.assertEqual(story_id, "story-001")
                self.assertEqual(path, p1)
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", "worktree-story-001"],
                    cwd=td,
                    capture_output=True,
                )


class TestFindClosingTeammateWorktreeCli(unittest.TestCase):
    """branching_cli find-closing-teammate-worktree emits ``<abs-path>\\t<branch>``
    for the live teammate worktree whose sprint.json story is `done`.

    Drives /xp-story-close's preload: no marker, no /xp-accept
    context-passing — discover the worktree implicitly from the (live
    worktree, done status) join. Tab delimiter: worktree paths can
    contain spaces on macOS; tab guarantees a single split point in
    bash parameter expansion. Empty stdout when no match; non-zero
    exit + stderr on multi-match (signals broken /xp-accept
    iteration — fail loud).
    """

    def _write_sprint(self, smm_dir: Path, stories):
        _seed_sprint_with_stories(smm_dir, stories)

    def _make_worktree(self, td, story_id):
        path = Path(td) / ".claude" / "worktrees" / f"worktree-{story_id}"
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", f"u/{story_id}-x", str(path), "HEAD"],
            cwd=td,
            capture_output=True,
            check=True,
        )
        return os.path.realpath(str(path))

    def _cleanup_worktree(self, td, name):
        subprocess.run(
            ["git", "worktree", "remove", "--force", name],
            cwd=td,
            capture_output=True,
        )

    def _run_branching(self, smm_dir, *args):
        script = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")
        return subprocess.run(
            [sys.executable, script, "--smm-dir", str(smm_dir), *args],
            capture_output=True,
            text=True,
            env=_GIT_ENV,
        )

    def test_emits_path_tab_branch_on_match(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            self._write_sprint(
                smm_dir, [("story-001", "done"), ("story-002", "in-progress")]
            )
            try:
                p1 = self._make_worktree(td, "story-001")
                self._make_worktree(td, "story-002")
                r = self._run_branching(
                    smm_dir, "find-closing-teammate-worktree", "--cwd", td
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), f"{p1}\tu/story-001-x")
            finally:
                self._cleanup_worktree(td, "worktree-story-001")
                self._cleanup_worktree(td, "worktree-story-002")

    def test_path_with_space_preserved_verbatim(self):
        """Path with a space round-trips verbatim under the tab delimiter."""
        with (
            tempfile.TemporaryDirectory() as parent,
            tempfile.TemporaryDirectory() as smm,
        ):
            td = _init_repo_in_spaced_parent(parent)
            smm_dir = Path(smm)
            self._write_sprint(smm_dir, [("story-001", "done")])
            try:
                p1 = self._make_worktree(td, "story-001")
                self.assertIn(" ", p1)
                r = self._run_branching(
                    smm_dir, "find-closing-teammate-worktree", "--cwd", td
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                line = r.stdout.strip()
                path, _, branch = line.rpartition("\t")
                self.assertEqual(path, p1)
                self.assertEqual(branch, "u/story-001-x")
            finally:
                self._cleanup_worktree(td, "worktree-story-001")

    def test_empty_stdout_when_solo(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            self._write_sprint(smm_dir, [("story-001", "done")])
            r = self._run_branching(
                smm_dir, "find-closing-teammate-worktree", "--cwd", td
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, "")

    def test_empty_stdout_when_no_done_status(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            self._write_sprint(smm_dir, [("story-001", "in-progress")])
            try:
                self._make_worktree(td, "story-001")
                r = self._run_branching(
                    smm_dir, "find-closing-teammate-worktree", "--cwd", td
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout, "")
            finally:
                self._cleanup_worktree(td, "worktree-story-001")

    def test_errors_on_multi_done_match(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            # Two done-status stories with live worktrees — broken iteration.
            self._write_sprint(smm_dir, [("story-001", "done"), ("story-002", "done")])
            try:
                self._make_worktree(td, "story-001")
                self._make_worktree(td, "story-002")
                r = self._run_branching(
                    smm_dir, "find-closing-teammate-worktree", "--cwd", td
                )
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertIn("story-001", r.stderr)
                self.assertIn("story-002", r.stderr)
            finally:
                self._cleanup_worktree(td, "worktree-story-001")
                self._cleanup_worktree(td, "worktree-story-002")


if __name__ == "__main__":
    unittest.main()
