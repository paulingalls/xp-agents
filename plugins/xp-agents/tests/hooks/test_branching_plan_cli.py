#!/usr/bin/env python3
"""Tests for branching.py — plan/free-branch CLI subcommands (E2E) and the
slug-drift regression.

Covers: get-primary, get-target, create-plan, create-free, list-free,
merge-branch CLI subcommands, and the create-sprint slug-drift regression.

Split from test_branching_plan.py — create_plan_branch/create_free_branch/
list_free_branches direct-call tests remain there.

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

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _branching_fixtures as _bf
import execution_plan_store

_GIT_ENV = _bf.GIT_ENV
_init_repo = _bf.init_repo
_get_current_branch = _bf.get_current_branch
_write_system_context = _bf.write_system_context
_seed_plan = _bf.seed_plan


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
            plan = execution_plan_store.load_plan_required(smm_dir)
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
