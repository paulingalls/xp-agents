#!/usr/bin/env python3
"""Tests for branching.py — plan/free-branch lifecycle.

Covers: create_plan_branch, create_free_branch, list_free_branches,
and their CLI subcommands.

Story branch lifecycle tests live in test_branching_lifecycle.py;
sprint branch tests in test_branching_sprint.py;
divergence detection in test_branching_divergence.py;
pure-helper unit tests in test_branching.py.
"""

import json
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
import execution_plan_store

_GIT_ENV = _bf.GIT_ENV
_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context
_seed_plan = _bf.seed_plan


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

    def test_resume_re_records_branch_into_plan(self):
        """Resume path mirrors create_sprint_branch: idempotently re-records.

        Debt 94522af75c37 — the prior on_create-only callback meant a plan
        regenerated post-creation would have plan.branch=null while the
        actual branch still existed. Re-recording on resume fixes any
        slug drift, matching the sprint primitive's behavior.
        """
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
            self.assertEqual(plan["branch"], "paul/plan-redesign")

    def test_resume_records_branch_when_plan_branch_was_null(self):
        """Plan regenerated post-creation: resume rescues the linkage."""
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
            _seed_plan(smm_dir)  # plan.branch is unset/null

            with patch("branching.identity.user_namespace", return_value="paul"):
                branching.create_plan_branch(td, "redesign", smm_dir)

            plan = execution_plan_store.load_plan(smm_dir)
            self.assertEqual(plan["branch"], "paul/plan-redesign")

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


_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts" / "branching.py")


def _run(args: list[str], smm_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, _SCRIPT, "--smm-dir", str(smm_dir), *args],
        capture_output=True,
        text=True,
    )


class TestPlanFreeCLI(unittest.TestCase):
    def test_get_primary_main_at_stage_2(self):
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            r = _run(["get-primary"], smm_dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "main")

    def test_get_primary_integration_at_stage_3(self):
        with tempfile.TemporaryDirectory() as smm:
            smm_dir = Path(smm)
            (smm_dir / "system_context.json").write_text(
                json.dumps(
                    {
                        "branching_strategy": {
                            "stage": 3,
                            "integration_branch": "develop",
                        }
                    }
                )
            )
            r = _run(["get-primary"], smm_dir)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "develop")

    def test_get_target_falls_back_to_primary(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            r = _run(["get-target", "--cwd", td], smm_dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "main")

    def test_create_plan_cli(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            _seed_plan(smm_dir)
            r = _run(
                ["create-plan", "--cwd", td, "--slug", "redesign"],
                smm_dir,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("test/plan-redesign", r.stdout)
            plan = execution_plan_store.load_plan(smm_dir)
            self.assertEqual(plan["branch"], "test/plan-redesign")

    def test_create_free_cli(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            r = _run(
                ["create-free", "--cwd", td, "--slug", "spike"],
                smm_dir,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("test/free-", r.stdout)
            self.assertIn("-spike", r.stdout)

    def test_list_free_cli(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )
            for n in ("test/free-2026-04-22-foo", "test/free-2026-04-23-bar"):
                subprocess.run(
                    ["git", "branch", n],
                    cwd=td,
                    capture_output=True,
                    check=True,
                )
            smm_dir = Path(smm)
            r = _run(["list-free", "--cwd", td], smm_dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            lines = r.stdout.strip().splitlines()
            self.assertIn("test/free-2026-04-22-foo", lines)
            self.assertIn("test/free-2026-04-23-bar", lines)

    def test_merge_branch_cli(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            main_branch = _get_current_branch(td)
            subprocess.run(
                ["git", "checkout", "-b", "test/sprint-031-feat"],
                cwd=td,
                capture_output=True,
                check=True,
            )
            (Path(td) / "f.txt").write_text("x")
            subprocess.run(["git", "add", "."], cwd=td, capture_output=True, check=True)
            subprocess.run(
                ["git", "commit", "-m", "feat"],
                cwd=td,
                capture_output=True,
                check=True,
                env=_GIT_ENV,
            )
            smm_dir = Path(smm)
            r = _run(
                [
                    "merge-branch",
                    "--cwd",
                    td,
                    "--branch",
                    "test/sprint-031-feat",
                    "--target",
                    main_branch,
                ],
                smm_dir,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            log = subprocess.run(
                ["git", "log", "--merges", "--oneline"],
                cwd=td,
                capture_output=True,
                text=True,
            )
            self.assertIn("test/sprint-031-feat", log.stdout)


class TestSlugBugRegression(unittest.TestCase):
    """Regression: arbitrary slug + get-base must find the recorded branch."""

    def test_slug_drift_does_not_break_lookup(self):
        import sprint_store

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as smm:
            _init_repo(td)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=td,
                capture_output=True,
            )
            smm_dir = Path(smm)
            _write_system_context(smm_dir, stage=2)
            sprint_store.save_sprint(
                smm_dir,
                {
                    "sprint_id": "sprint-031",
                    "goal": "totally different goal text",
                    "started": "2026-04-24",
                    "milestone": "M-1",
                    "stories": [
                        {
                            "id": "story-001",
                            "title": "T",
                            "status": "ready",
                            "dependencies": [],
                            "milestone_ref": "",
                            "design_sources": "",
                            "context": "",
                            "file_domain": [],
                            "interface_contracts": [],
                            "acceptance_criteria": [],
                        }
                    ],
                },
            )

            r = _run(
                [
                    "create-sprint",
                    "--cwd",
                    td,
                    "--sprint",
                    "sprint-031",
                    "--slug",
                    "arbitrary-and-unrelated",
                ],
                smm_dir,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("test/sprint-031-arbitrary-and-unrelated", r.stdout)

            r = _run(["get-base", "--cwd", td], smm_dir)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(
                r.stdout.strip(), "test/sprint-031-arbitrary-and-unrelated"
            )


if __name__ == "__main__":
    unittest.main()
