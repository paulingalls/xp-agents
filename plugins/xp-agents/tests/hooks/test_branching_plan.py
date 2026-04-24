#!/usr/bin/env python3
"""Tests for branching.py — plan/free-branch lifecycle.

Covers: create_plan_branch (plan branches recorded into execution_plan.json),
plus future create_free_branch / list_free_branches.

Story branch lifecycle tests live in test_branching_lifecycle.py;
sprint branch tests in test_branching_sprint.py;
pure-helper unit tests in test_branching.py.
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
import execution_plan_store

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


def _init_repo(td: str) -> None:
    subprocess.run(["git", "init", td], capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=td,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=td,
        capture_output=True,
        check=True,
    )
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


def _seed_plan(smm_dir: Path) -> None:
    plan = {
        "title": "Test Plan",
        "sources": [],
        "overview": "ov",
        "milestones": [],
    }
    execution_plan_store.save_plan(smm_dir, plan, enforce_budget=False)


class TestCreatePlanBranch(unittest.TestCase):
    def test_creates_off_primary_at_stage_2(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            primary = _get_current_branch(td)
            primary_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                patch("branching.get_primary_branch", return_value=primary),
            ):
                result = branching.create_plan_branch(td, "redesign", smm_dir)

            self.assertEqual(result, "paul/plan-redesign")
            self.assertEqual(_get_current_branch(td), "paul/plan-redesign")
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(sha, primary_sha)

    def test_records_branch_in_plan(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)

            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_plan_branch(td, "redesign", smm_dir)

            plan = execution_plan_store.load_plan(smm_dir)
            self.assertEqual(plan["branch"], "paul/plan-redesign")

    def test_resume_does_not_record(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/plan-redesign"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)
            plan = execution_plan_store.load_plan(smm_dir)
            plan["branch"] = "preexisting/value"
            execution_plan_store.save_plan(smm_dir, plan, enforce_budget=False)

            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.create_plan_branch(td, "redesign", smm_dir)

            self.assertEqual(result, "paul/plan-redesign")
            plan = execution_plan_store.load_plan(smm_dir)
            self.assertEqual(plan["branch"], "preexisting/value")

    def test_skips_at_stage_below_2(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=1)

            result = branching.create_plan_branch(td, "redesign", Path(smm))
            self.assertIsNone(result)

    def test_dirty_tree_exits(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            (Path(td) / "dirty.txt").write_text("uncommitted")
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                self.assertRaises(SystemExit),
            ):
                branching.create_plan_branch(td, "redesign", smm_dir)


class TestCreateFreeBranch(unittest.TestCase):
    def test_creates_with_date_pattern(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            primary = _get_current_branch(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                patch("branching.get_primary_branch", return_value=primary),
                patch("branching._utc_today_iso", return_value="2026-04-24"),
            ):
                result = branching.create_free_branch(td, "spike-foo", smm_dir)

            self.assertEqual(result, "paul/free-2026-04-24-spike-foo")
            self.assertEqual(_get_current_branch(td), "paul/free-2026-04-24-spike-foo")

    def test_creates_off_primary(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            primary = _get_current_branch(td)
            primary_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                patch("branching.get_primary_branch", return_value=primary),
                patch("branching._utc_today_iso", return_value="2026-04-24"),
            ):
                branching.create_free_branch(td, "spike", smm_dir)

            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=td, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(sha, primary_sha)

    def test_resume_existing_branch(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "branch", "paul/free-2026-04-24-spike"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                patch("branching._utc_today_iso", return_value="2026-04-24"),
            ):
                result = branching.create_free_branch(td, "spike", smm_dir)

            self.assertEqual(result, "paul/free-2026-04-24-spike")
            self.assertEqual(_get_current_branch(td), "paul/free-2026-04-24-spike")

    def test_skips_at_stage_0(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            _write_system_context(Path(smm), stage=0)

            result = branching.create_free_branch(td, "spike", Path(smm))
            self.assertIsNone(result)

    def test_creates_at_stage_1(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            primary = _get_current_branch(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=1)

            with (
                patch("branching.identity.user_namespace", return_value="paul"),
                patch("branching.get_primary_branch", return_value=primary),
                patch("branching._utc_today_iso", return_value="2026-04-24"),
            ):
                result = branching.create_free_branch(td, "spike", smm_dir)

            self.assertEqual(result, "paul/free-2026-04-24-spike")


class TestListFreeBranches(unittest.TestCase):
    def _make_branches(self, td: str, names: list[str]) -> None:
        for n in names:
            subprocess.run(
                ["git", "branch", n], cwd=td, capture_output=True, check=True
            )

    def test_returns_matching_branches(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            self._make_branches(
                td,
                [
                    "paul/free-2026-04-24-spike",
                    "paul/free-2026-04-22-other",
                    "paul/story-001-foo",
                    "alice/free-2026-04-24-mine",
                ],
            )
            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.list_free_branches(td)
            self.assertEqual(
                sorted(result),
                ["paul/free-2026-04-22-other", "paul/free-2026-04-24-spike"],
            )

    def test_excludes_current_branch(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            subprocess.run(
                ["git", "checkout", "-b", "paul/free-2026-04-24-current"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "branch", "paul/free-2026-04-23-other"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.list_free_branches(td)
            self.assertEqual(result, ["paul/free-2026-04-23-other"])

    def test_returns_empty_when_no_free_branches(self):
        with tempfile.TemporaryDirectory() as td:
            _init_repo(td)
            with patch("branching.identity.user_namespace", return_value="paul"):
                result = branching.list_free_branches(td)
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
