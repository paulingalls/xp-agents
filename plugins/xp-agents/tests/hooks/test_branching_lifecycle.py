#!/usr/bin/env python3
"""Tests for branching.py — git-operation lifecycle tests.

Covers: is_worktree_clean, branch_exists, create_story_branch,
merge_story_branch, delete_branch, CLI (E2E).

Split from test_branching.py — pure-function unit tests remain there.
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

import _branching_fixtures as _bf
import branching

_GIT_ENV = _bf.GIT_ENV
_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context


def _make_feature_commit(td: str, filename: str = "feature.txt") -> None:
    (Path(td) / filename).write_text(f"content of {filename}")
    subprocess.run(["git", "add", "."], cwd=td, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_GIT_ENV,
    )


class TestIsWorktreeClean(unittest.TestCase):
    def test_clean_repo(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertTrue(branching.is_worktree_clean(td))

    def test_dirty_repo(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            self.assertFalse(branching.is_worktree_clean(td))


class TestBranchExists(unittest.TestCase):
    def test_existing_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "feature-x"], cwd=td, capture_output=True, check=True
            )
            self.assertTrue(branching.branch_exists(td, "feature-x"))

    def test_nonexistent_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self.assertFalse(branching.branch_exists(td, "no-such-branch"))


class TestCreateStoryBranch(unittest.TestCase):
    def test_creates_and_checks_out_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "branch-lifecycle", smm_dir
                )

            self.assertEqual(result, "paul/story-001-branch-lifecycle")
            self.assertEqual(_get_current_branch(td), "paul/story-001-branch-lifecycle")

    def test_skips_at_stage_zero(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=0)

            result = branching.create_story_branch(td, "story-001", "test", Path(smm))
            self.assertIsNone(result)

    def test_skips_when_no_system_context(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)

            result = branching.create_story_branch(td, "story-001", "test", Path(smm))
            self.assertIsNone(result)

    def test_resume_existing_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/story-001-resume"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "resume", smm_dir
                )

            self.assertEqual(result, "paul/story-001-resume")
            self.assertEqual(_get_current_branch(td), "paul/story-001-resume")

    def test_raises_when_dirty(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                self.assertRaises(SystemExit),
            ):
                branching.create_story_branch(td, "story-001", "dirty", smm_dir)

    def test_exits_when_existing_checkout_fails(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            fail_result = subprocess.CompletedProcess(
                ["git", "checkout"], 1, "", "error: conflict"
            )

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                patch("branching.branch_exists", return_value=True),
                patch("branching._git", return_value=fail_result),
                self.assertRaises(SystemExit),
            ):
                branching.create_story_branch(td, "story-001", "conflict", smm_dir)


class TestMergeStoryBranch(unittest.TestCase):
    def test_merge_commit_created(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/story-001-test"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td)

            branching.merge_story_branch(td, "paul/story-001-test", target=main_branch)

            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("paul/story-001-test", merges.stdout)

    def test_merge_preserves_history(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/story-002-hist"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            for i in range(3):
                _make_feature_commit(td, f"file{i}.txt")

            branching.merge_story_branch(td, "paul/story-002-hist", target=main_branch)

            log = subprocess.run(
                ["git", "log", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            for i in range(3):
                self.assertIn(f"file{i}.txt", log.stdout)


class TestMergeSprintBranch(unittest.TestCase):
    def test_merges_into_target(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/sprint-027-feat"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td)

            branching.merge_sprint_branch(
                td, "paul/sprint-027-feat", target=main_branch
            )

            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("paul/sprint-027-feat", merges.stdout)
            self.assertEqual(_get_current_branch(td), main_branch)

    def test_exits_on_merge_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            (Path(td) / "shared.txt").write_text("from-main")
            subprocess.run(
                ["git", "add", "shared.txt"], cwd=td, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "main side"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )

            subprocess.run(
                ["git", "checkout", "-b", "paul/sprint-027-conflict", "HEAD~1"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            (Path(td) / "shared.txt").write_text("from-sprint")
            subprocess.run(
                ["git", "add", "shared.txt"], cwd=td, capture_output=True, check=True
            )
            subprocess.run(
                ["git", "commit", "-m", "sprint side"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )

            with self.assertRaises(SystemExit):
                branching.merge_sprint_branch(
                    td, "paul/sprint-027-conflict", target=main_branch
                )


class TestDeleteBranch(unittest.TestCase):
    def test_deletes_merged_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/story-001-del"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td, "f.txt")

            subprocess.run(
                ["git", "checkout", main_branch],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "merge", "--no-ff", "paul/story-001-del", "-m", "merge"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )

            result = branching.delete_branch(td, "paul/story-001-del")
            self.assertTrue(result)
            self.assertFalse(branching.branch_exists(td, "paul/story-001-del"))


class TestCLI(unittest.TestCase):
    """E2E: full create → merge → delete cycle via CLI subprocess."""

    def test_full_lifecycle(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            script = str(
                Path(__file__).parent.parent.parent / "scripts" / "branching.py"
            )

            # Create story branch
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "create",
                    "--cwd",
                    td,
                    "--story",
                    "story-001",
                    "--slug",
                    "lifecycle-test",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("test/story-001-lifecycle-test", r.stdout)

            _make_feature_commit(td)

            # Merge story branch
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "merge",
                    "--cwd",
                    td,
                    "--branch",
                    "test/story-001-lifecycle-test",
                    "--target",
                    main_branch,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            # Delete story branch
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "delete",
                    "--cwd",
                    td,
                    "--branch",
                    "test/story-001-lifecycle-test",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            # Verify merge commit exists and branch is gone
            merges = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("story-001-lifecycle-test", merges.stdout)

            branches = subprocess.run(
                ["git", "branch"], cwd=td, capture_output=True, text=True
            )
            self.assertNotIn("story-001-lifecycle-test", branches.stdout)

    def test_stage_command(self):
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            script = str(
                Path(__file__).parent.parent.parent / "scripts" / "branching.py"
            )
            r = subprocess.run(
                [sys.executable, script, "--smm-dir", str(smm_dir), "stage"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0)
            self.assertIn("2", r.stdout)


if __name__ == "__main__":
    unittest.main()
