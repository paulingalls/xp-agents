#!/usr/bin/env python3
"""Tests for branching.py — sprint branch lifecycle tests.

Covers: create_sprint_branch, get_story_base_branch, sprint CLI commands.

Story branch lifecycle tests are in test_branching_lifecycle.py.
Pure-function unit tests are in test_branching.py.
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


def _write_sprint_json(
    smm_dir: Path, sprint_id: str, goal: str, started: str = "2026-04-22"
) -> None:
    import sprint_store

    data = {
        "sprint_id": sprint_id,
        "goal": goal,
        "started": started,
        "milestone": "test",
        "stories": [
            {
                "id": "story-001",
                "title": "Test",
                "status": "ready",
                "dependencies": [],
                "milestone_ref": "test",
                "design_sources": "test",
                "context": "test",
                "file_domain": [],
                "interface_contracts": [],
                "acceptance_criteria": ["test"],
            }
        ],
    }
    sprint_store.save_sprint(smm_dir, data)


class TestCreateSprintBranch(unittest.TestCase):
    def test_creates_at_stage_2(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_sprint_branch(
                    td, "sprint-027", "integration", smm_dir
                )

            self.assertEqual(result, "paul/sprint-027-integration")
            self.assertEqual(_get_current_branch(td), "paul/sprint-027-integration")

    def test_skips_at_stage_0(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=0)

            result = branching.create_sprint_branch(td, "sprint-027", "test", Path(smm))
            self.assertIsNone(result)

    def test_skips_at_stage_1(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=1)

            result = branching.create_sprint_branch(td, "sprint-027", "test", Path(smm))
            self.assertIsNone(result)

    def test_resume_existing_sprint_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/sprint-027-resume"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_sprint_branch(
                    td, "sprint-027", "resume", smm_dir
                )

            self.assertEqual(result, "paul/sprint-027-resume")
            self.assertEqual(_get_current_branch(td), "paul/sprint-027-resume")

    def test_dirty_tree_exits(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                self.assertRaises(SystemExit),
            ):
                branching.create_sprint_branch(td, "sprint-027", "dirty", smm_dir)


class TestCreateSprintBranchRecordsBranchName(unittest.TestCase):
    def test_records_after_create(self):
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-031", "branch lifecycle")

            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_sprint_branch(td, "sprint-031", "lifecycle", smm_dir)

            sprint = sprint_store.load_sprint(smm_dir)
            self.assertEqual(sprint["branch_name"], "paul/sprint-031-lifecycle")

    def test_resume_re_records_fixing_drift(self):
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/sprint-031-actual-name"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-031", "ignored goal")
            sprint = sprint_store.load_sprint(smm_dir)
            sprint["branch_name"] = "paul/sprint-031-stale"
            sprint_store.save_sprint(smm_dir, sprint, enforce_budget=False)

            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_sprint_branch(td, "sprint-031", "actual-name", smm_dir)

            sprint = sprint_store.load_sprint(smm_dir)
            self.assertEqual(sprint["branch_name"], "paul/sprint-031-actual-name")

    def test_no_sprint_no_record_no_error(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_sprint_branch(
                    td, "sprint-031", "no-sprint-yet", smm_dir
                )

            self.assertEqual(result, "paul/sprint-031-no-sprint-yet")


def _seed_plan(smm_dir: Path, branch: str | None = None) -> None:
    import execution_plan_store

    plan = {
        "title": "T",
        "sources": [],
        "overview": "o",
        "milestones": [],
    }
    if branch is not None:
        plan["branch"] = branch
    execution_plan_store.save_plan(smm_dir, plan, enforce_budget=False)


def _commit_on_branch(td: str, branch: str, filename: str) -> str:
    """Add a commit on `branch`, return its SHA."""
    subprocess.run(["git", "checkout", branch], cwd=td, capture_output=True, check=True)
    (Path(td) / filename).write_text(filename)
    subprocess.run(["git", "add", filename], cwd=td, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_GIT_ENV,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
    ).stdout.strip()


class TestCreateSprintBranchPlanBase(unittest.TestCase):
    def test_forks_off_plan_branch_when_set_and_exists(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "checkout", "-b", "paul/plan-redesign"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            plan_sha = _commit_on_branch(td, "paul/plan-redesign", "plan-only.txt")
            subprocess.run(["git", "checkout", "main"], cwd=td, capture_output=True)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir, branch="paul/plan-redesign")

            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_sprint_branch(td, "sprint-031", "feat", smm_dir)

            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(head, plan_sha)

    def test_forks_off_head_when_no_plan_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            head_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)

            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_sprint_branch(td, "sprint-031", "feat", smm_dir)

            new_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(new_sha, head_sha)

    def test_forks_off_head_when_plan_branch_missing_locally(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            head_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir, branch="paul/plan-nonexistent")

            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_sprint_branch(td, "sprint-031", "feat", smm_dir)

            new_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(new_sha, head_sha)


class TestGetStoryBaseBranch(unittest.TestCase):
    def test_returns_sprint_branch_at_stage_2(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-027", "integration test")

            subprocess.run(
                ["git", "checkout", "-b", "paul/sprint-027-integration-test"],
                cwd=td,
                capture_output=True,
            )
            subprocess.run(
                ["git", "checkout", "-"],
                cwd=td,
                capture_output=True,
            )

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.get_story_base_branch(smm_dir, td)

            self.assertEqual(result, "paul/sprint-027-integration-test")

    def test_returns_main_at_stage_1(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)
            _write_sprint_json(smm_dir, "sprint-027", "test")

            result = branching.get_story_base_branch(smm_dir, td)
            self.assertEqual(result, "main")

    def test_returns_main_at_stage_0(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=0)

            result = branching.get_story_base_branch(Path(smm), td)
            self.assertEqual(result, "main")

    def test_returns_main_when_no_sprint(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            result = branching.get_story_base_branch(smm_dir, td)
            self.assertEqual(result, "main")

    def test_returns_main_when_sprint_branch_doesnt_exist(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-027", "nonexistent")

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.get_story_base_branch(smm_dir, td)

            self.assertEqual(result, "main")

    def test_prefers_stored_branch_name_over_slugify(self):
        """Stored branch_name wins even when goal-slug would produce a
        different name. Defends against slug drift between create time and
        lookup time (e.g. goal text edited after the branch was created)."""
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/sprint-027-actual-name"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-027", "edited goal text")
            sprint = sprint_store.load_sprint(smm_dir)
            sprint["branch_name"] = "paul/sprint-027-actual-name"
            sprint_store.save_sprint(smm_dir, sprint, enforce_budget=False)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.get_story_base_branch(smm_dir, td)

            self.assertEqual(result, "paul/sprint-027-actual-name")

    def test_falls_back_to_slugify_when_stored_branch_missing_locally(self):
        """Legacy sprints without branch_name (or stale recorded names that
        no longer exist) still resolve via the goal-slug reconstruction."""
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/sprint-027-legacy"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-027", "legacy")
            sprint = sprint_store.load_sprint(smm_dir)
            sprint["branch_name"] = "paul/sprint-027-deleted"
            sprint_store.save_sprint(smm_dir, sprint, enforce_budget=False)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.get_story_base_branch(smm_dir, td)

            self.assertEqual(result, "paul/sprint-027-legacy")


class TestSprintCLI(unittest.TestCase):
    def test_create_sprint_cli(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )

            script = str(
                Path(__file__).parent.parent.parent / "scripts" / "branching.py"
            )
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "create-sprint",
                    "--cwd",
                    td,
                    "--sprint",
                    "sprint-027",
                    "--slug",
                    "integration",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("test/sprint-027-integration", r.stdout)
            self.assertEqual(_get_current_branch(td), "test/sprint-027-integration")

    def test_get_base_cli(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _write_sprint_json(smm_dir, "sprint-027", "integration test")

            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )

            subprocess.run(
                ["git", "checkout", "-b", "test/sprint-027-integration-test"],
                cwd=td,
                capture_output=True,
            )
            subprocess.run(
                ["git", "checkout", "-"],
                cwd=td,
                capture_output=True,
            )

            script = str(
                Path(__file__).parent.parent.parent / "scripts" / "branching.py"
            )
            r = subprocess.run(
                [
                    sys.executable,
                    script,
                    "--smm-dir",
                    str(smm_dir),
                    "get-base",
                    "--cwd",
                    td,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("test/sprint-027-integration-test", r.stdout.strip())


if __name__ == "__main__":
    unittest.main()
