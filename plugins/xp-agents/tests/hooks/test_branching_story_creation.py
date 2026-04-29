#!/usr/bin/env python3
"""Tests for branching.create_story_branch — story-branch creation/resume."""

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

_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context
_make_feature_commit = _bf.append_commit


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

    def test_resume_fast_forwards_when_behind_base(self):
        """Story branch resumed mid-sprint must fast-forward to the
        current sprint base, not snap to the stale scaffold-time HEAD.

        Reproduces concern dc0340ac5582: sprint-start scaffolds story
        branches off pre-iter HEAD; later, the sprint base advances
        (e.g., a prior story was merged in); resuming the story branch
        without fast-forward leaves it on the stale base — exactly what
        happened in this session when story-002 had to manually rebase
        onto story-001's commits.
        """
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            # Scaffold-time: create the story branch off the original main tip.
            subprocess.run(
                ["git", "branch", "paul/story-001-ff"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            # Base advances after scaffold.
            _make_feature_commit(td, "base-advance.txt")
            advanced_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            # Resume the scaffolded branch with the advanced base.
            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(td, "story-001", "ff", smm_dir)

            self.assertEqual(result, "paul/story-001-ff")
            self.assertEqual(_get_current_branch(td), "paul/story-001-ff")
            resumed_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(
                resumed_sha,
                advanced_sha,
                "Resumed story branch must fast-forward to current base; "
                f"expected {advanced_sha}, got {resumed_sha} (stale)",
            )

    def test_resume_preserves_unique_commits_no_rebase(self):
        """Story branch with its own commits ahead of base must NOT be
        silently rebased — that could lose work or surface conflicts the
        agent didn't ask to resolve. Auto-fast-forward only when safe.
        """
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            # Create + check out the story branch, make a unique commit on it.
            subprocess.run(
                ["git", "checkout", "-b", "paul/story-001-ahead"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            _make_feature_commit(td, "story-only.txt")
            story_tip = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            # Switch back so we can resume.
            subprocess.run(
                ["git", "checkout", "main"],
                cwd=td,
                capture_output=True,
                check=True,
            )

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "ahead", smm_dir
                )

            self.assertEqual(result, "paul/story-001-ahead")
            resumed_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(
                resumed_sha,
                story_tip,
                "Resumed story branch with unique commits must not be "
                "rewound or rebased — story tip must be preserved.",
            )

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


class TestCreateStoryBranchWithBase(unittest.TestCase):
    def test_forks_from_explicit_base(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _make_feature_commit(td, "first.txt")
            base_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            _make_feature_commit(td, "second.txt")

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-002", "chained", smm_dir, base=base_sha
                )

            self.assertEqual(result, "paul/story-002-chained")
            parent_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(parent_sha, base_sha)

    def test_default_base_uses_story_base_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_story_branch(
                    td, "story-001", "default", smm_dir
                )

            self.assertEqual(result, "paul/story-001-default")
            self.assertEqual(_get_current_branch(td), "paul/story-001-default")

    def test_cli_base_flag_passthrough(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _make_feature_commit(td, "first.txt")
            base_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            _make_feature_commit(td, "second.txt")

            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            cli = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")
            env = {**_bf.GIT_ENV, "USER": "paul"}
            result = subprocess.run(
                [
                    sys.executable,
                    cli,
                    "--smm-dir",
                    str(smm_dir),
                    "create",
                    "--cwd",
                    td,
                    "--story",
                    "story-002",
                    "--slug",
                    "cli-base",
                    "--base",
                    base_sha,
                ],
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("story-002-cli-base", result.stdout)
            branch = result.stdout.strip().split(": ", 1)[1]
            head_sha = subprocess.run(
                ["git", "rev-parse", branch],
                cwd=td,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            self.assertEqual(head_sha, base_sha)


if __name__ == "__main__":
    unittest.main()
