#!/usr/bin/env python3
"""Capstone integration tests for team-scenario branching (M-5).

Exercises pre-existing branch detection and divergence detection via
CLI subprocess calls in temp git repos. Unit tests for the library
functions live in test_branching_lifecycle.py and test_branching_divergence.py.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT

_BRANCHING = _PLUGIN_ROOT / "scripts" / "branching.py"
_PLAN_CLI = _PLUGIN_ROOT / "smm" / "plan_cli.py"

sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
import branching  # noqa: E402

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "test@test.com",
    "PATH": subprocess.run(
        ["bash", "-c", "echo $PATH"], capture_output=True, text=True
    ).stdout.strip(),
}


def _init_repo(td: str) -> None:
    subprocess.run(["git", "init", "-b", "main", td], capture_output=True, check=True)
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


def _write_system_context(smm_dir: Path, stage: int) -> None:
    ctx = {"project_name": "test", "branching_strategy": {"stage": stage}}
    (smm_dir / "system_context.json").write_text(json.dumps(ctx))


def _make_commit(td: str, filename: str) -> None:
    (Path(td) / filename).write_text(f"content of {filename}")
    subprocess.run(["git", "add", "."], cwd=td, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"add {filename}"],
        cwd=td,
        capture_output=True,
        check=True,
        env=_GIT_ENV,
    )


def _run_branching(smm_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_BRANCHING), "--smm-dir", str(smm_dir), *args],
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )


def _seed_plan(smm_dir: Path, branch: str | None = None) -> None:
    plan = json.dumps(
        {
            "title": "Test Plan",
            "sources": [],
            "overview": "ov",
            "milestones": [],
            **({"branch": branch} if branch else {}),
        }
    )
    subprocess.run(
        [sys.executable, str(_PLAN_CLI), "--smm-dir", str(smm_dir), "create"],
        input=plan,
        capture_output=True,
        text=True,
        check=True,
    )


class TestPreExistingSprintBranch(unittest.TestCase):
    """CLI create-sprint reports created/resumed prefix."""

    def test_new_sprint_branch_reports_created(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            r = _run_branching(
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
            self.assertTrue(r.stdout.strip().startswith("created:"))
            self.assertIn("sprint-099", r.stdout)

    def test_existing_sprint_branch_reports_resumed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            subprocess.run(
                ["git", "branch", "test/sprint-099-existing"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            r = _run_branching(
                smm_dir,
                "create-sprint",
                "--cwd",
                td,
                "--sprint",
                "sprint-099",
                "--slug",
                "existing",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip().startswith("resumed:"))


class TestPreExistingPlanBranch(unittest.TestCase):
    """CLI create-plan reports created/resumed prefix."""

    def test_new_plan_branch_reports_created(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)

            r = _run_branching(
                smm_dir,
                "create-plan",
                "--cwd",
                td,
                "--slug",
                "new-plan",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip().startswith("created:"))

    def test_existing_plan_branch_reports_resumed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)

            subprocess.run(
                ["git", "branch", "test/plan-existing"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            r = _run_branching(
                smm_dir,
                "create-plan",
                "--cwd",
                td,
                "--slug",
                "existing",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip().startswith("resumed:"))


class TestPreExistingStoryBranch(unittest.TestCase):
    """CLI create reports created/resumed prefix for story branches."""

    def test_new_story_branch_reports_created(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            r = _run_branching(
                smm_dir,
                "create",
                "--cwd",
                td,
                "--story",
                "story-099",
                "--slug",
                "new-story",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip().startswith("created:"))
            self.assertIn("story-099", r.stdout)

    def test_existing_story_branch_reports_resumed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            subprocess.run(
                ["git", "branch", "test/story-099-existing"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            r = _run_branching(
                smm_dir,
                "create",
                "--cwd",
                td,
                "--story",
                "story-099",
                "--slug",
                "existing",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip().startswith("resumed:"))


class TestPreExistingFreeBranch(unittest.TestCase):
    """CLI create-free reports created/resumed prefix."""

    def test_new_free_branch_reports_created(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            r = _run_branching(
                smm_dir,
                "create-free",
                "--cwd",
                td,
                "--slug",
                "new-free",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip().startswith("created:"))
            self.assertIn("free-", r.stdout)

    def test_existing_free_branch_reports_resumed(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            existing_name = branching.free_branch_name("test", "existing")
            subprocess.run(
                ["git", "branch", existing_name],
                cwd=td,
                capture_output=True,
                check=True,
            )
            r = _run_branching(
                smm_dir,
                "create-free",
                "--cwd",
                td,
                "--slug",
                "existing",
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.strip().startswith("resumed:"))


class TestPlanDivergenceIntegration(unittest.TestCase):
    """CLI check-divergence outputs JSON with/without warning."""

    def _setup_diverged(self, td, smm_dir, commits_behind):
        _init_repo(td)
        _write_system_context(smm_dir, stage=2)

        subprocess.run(
            ["git", "checkout", "-b", "test/plan-feat"],
            cwd=td,
            capture_output=True,
            check=True,
        )
        _make_commit(td, "plan-work.txt")
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=td,
            capture_output=True,
            check=True,
        )
        _seed_plan(smm_dir, branch="test/plan-feat")

        for i in range(commits_behind):
            _make_commit(td, f"primary-{i}.txt")

    def test_no_plan_branch_reports_no_plan(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)

            r = _run_branching(smm_dir, "check-divergence", "--cwd", td)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "No plan branch found")

    def test_below_threshold_no_warning(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, 5)

            r = _run_branching(smm_dir, "check-divergence", "--cwd", td)
            self.assertEqual(r.returncode, 0)
            data = json.loads(r.stdout)
            self.assertEqual(data["commits_behind"], 5)
            self.assertNotIn("warning", data)

    def test_at_threshold_has_warning_with_merge(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, 10)

            r = _run_branching(smm_dir, "check-divergence", "--cwd", td)
            self.assertEqual(r.returncode, 0)
            data = json.loads(r.stdout)
            self.assertEqual(data["commits_behind"], 10)
            self.assertIn("warning", data)
            self.assertIn("merge", data["suggestion"].lower())
            self.assertNotIn("rebase", data["suggestion"].lower())

    def test_custom_threshold(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            self._setup_diverged(td, smm_dir, 3)

            r = _run_branching(
                smm_dir,
                "check-divergence",
                "--cwd",
                td,
                "--threshold",
                "3",
            )
            self.assertEqual(r.returncode, 0)
            data = json.loads(r.stdout)
            self.assertIn("warning", data)


if __name__ == "__main__":
    unittest.main()
