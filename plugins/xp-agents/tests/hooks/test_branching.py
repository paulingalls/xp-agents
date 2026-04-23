#!/usr/bin/env python3
"""Tests for branching.py — branch lifecycle operations.

Covers: branch_name, get_branching_stage, is_protected_branch,
extract_commit_message, is_escape_hatch_commit, is_worktree_clean,
branch_exists, create_story_branch, merge_story_branch, delete_branch, CLI.
"""

import json
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

import branching

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _init_repo(td: str) -> None:
    subprocess.run(["git", "init", td], capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_GIT_ENV,
    )


def _get_current_branch(cwd: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_system_context(smm_dir: Path, stage: int) -> None:
    ctx = {"project_name": "test", "branching_strategy": {"stage": stage}}
    (smm_dir / "system_context.json").write_text(json.dumps(ctx))


def _make_feature_commit(td: str, filename: str = "feature.txt") -> None:
    (Path(td) / filename).write_text(f"content of {filename}")
    subprocess.run(["git", "add", "."], cwd=td, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=td,
        capture_output=True,
        env=_GIT_ENV,
    )


class TestBranchName(unittest.TestCase):
    def test_basic_format(self):
        result = branching.branch_name("paul", "story-001", "schema-validation")
        self.assertEqual(result, "paul/story-001-schema-validation")

    def test_slug_sanitization(self):
        result = branching.branch_name("paul", "story-002", "Add Feature!!!")
        self.assertEqual(result, "paul/story-002-add-feature")

    def test_uppercase_lowered(self):
        result = branching.branch_name("Paul", "story-003", "CLI")
        self.assertEqual(result, "Paul/story-003-cli")

    def test_empty_slug(self):
        result = branching.branch_name("paul", "story-004", "---")
        self.assertEqual(result, "paul/story-004-")


class TestGetBranchingStage(unittest.TestCase):
    def test_no_system_context_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(branching.get_branching_stage(Path(td)), 0)

    def test_no_branching_strategy_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "system_context.json").write_text(
                json.dumps({"project_name": "test"})
            )
            self.assertEqual(branching.get_branching_stage(Path(td)), 0)

    def test_returns_declared_stage(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = {
                "project_name": "test",
                "branching_strategy": {"stage": 2},
            }
            (Path(td) / "system_context.json").write_text(json.dumps(ctx))
            self.assertEqual(branching.get_branching_stage(Path(td)), 2)

    def test_stage_zero_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = {
                "project_name": "test",
                "branching_strategy": {"stage": 0},
            }
            (Path(td) / "system_context.json").write_text(json.dumps(ctx))
            self.assertEqual(branching.get_branching_stage(Path(td)), 0)


class TestIsProtectedBranch(unittest.TestCase):
    def test_main_protected_at_stage_1(self):
        self.assertTrue(branching.is_protected_branch(1, "main"))

    def test_master_protected_at_stage_1(self):
        self.assertTrue(branching.is_protected_branch(1, "master"))

    def test_main_protected_at_stage_2(self):
        self.assertTrue(branching.is_protected_branch(2, "main"))

    def test_not_protected_at_stage_0(self):
        self.assertFalse(branching.is_protected_branch(0, "main"))

    def test_feature_branch_not_protected(self):
        self.assertFalse(branching.is_protected_branch(1, "paul/story-001-feat"))

    def test_empty_branch_not_protected(self):
        self.assertFalse(branching.is_protected_branch(1, ""))


class TestExtractCommitMessage(unittest.TestCase):
    def test_double_quoted(self):
        self.assertEqual(
            branching.extract_commit_message('git commit -m "fix bug"'),
            "fix bug",
        )

    def test_single_quoted(self):
        self.assertEqual(
            branching.extract_commit_message("git commit -m 'add feature'"),
            "add feature",
        )

    def test_no_m_flag(self):
        self.assertIsNone(branching.extract_commit_message("git commit"))

    def test_heredoc_style(self):
        cmd = """git commit -m "$(cat <<'EOF'
[release] bump version

Co-Authored-By: Claude
EOF
)" """
        result = branching.extract_commit_message(cmd)
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("[release]"))

    def test_empty_message(self):
        self.assertEqual(
            branching.extract_commit_message('git commit -m ""'),
            "",
        )

    def test_message_with_special_chars(self):
        self.assertEqual(
            branching.extract_commit_message('git commit -m "[chore] update deps"'),
            "[chore] update deps",
        )


class TestIsEscapeHatchCommit(unittest.TestCase):
    def test_release_prefix(self):
        self.assertTrue(
            branching.is_escape_hatch_commit('git commit -m "[release] v1.0"')
        )

    def test_chore_prefix(self):
        self.assertTrue(
            branching.is_escape_hatch_commit('git commit -m "[chore] cleanup"')
        )

    def test_case_insensitive(self):
        self.assertTrue(
            branching.is_escape_hatch_commit('git commit -m "[Release] v2.0"')
        )

    def test_no_prefix(self):
        self.assertFalse(branching.is_escape_hatch_commit('git commit -m "fix bug"'))

    def test_no_m_flag(self):
        self.assertFalse(branching.is_escape_hatch_commit("git commit"))

    def test_prefix_not_at_start(self):
        self.assertFalse(
            branching.is_escape_hatch_commit('git commit -m "fix [release] tag"')
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
            subprocess.run(["git", "branch", "feature-x"], cwd=td, capture_output=True)
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


class TestDeleteBranch(unittest.TestCase):
    def test_deletes_merged_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            main_branch = _get_current_branch(td)

            subprocess.run(
                ["git", "checkout", "-b", "paul/story-001-del"],
                cwd=td,
                capture_output=True,
            )
            _make_feature_commit(td, "f.txt")

            subprocess.run(
                ["git", "checkout", main_branch], cwd=td, capture_output=True
            )
            subprocess.run(
                ["git", "merge", "--no-ff", "paul/story-001-del", "-m", "merge"],
                cwd=td,
                capture_output=True,
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

            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )

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
