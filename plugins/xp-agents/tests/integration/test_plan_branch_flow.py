#!/usr/bin/env python3
"""End-to-end integration tests for the plan-branch flow.

Capstone for sprint-031 / M1: exercises the surfaces shipped by stories
001 (plan_cli set-branch / get-branch / is-plan-complete) and 002
(branching.py create-plan / create-sprint / get-target + atomic
branch_name recording) via subprocess CLI calls in a temp git repo.

Story 001 and 002 each have their own focused unit tests; this file
proves the surfaces compose correctly through the slug-bug fix.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _bases import _PLUGIN_ROOT
from conftest import _IntegrationTestCase

_PLAN_CLI = _PLUGIN_ROOT / "smm" / "plan_cli.py"
_BRANCHING = _PLUGIN_ROOT / "scripts" / "branching.py"


def _write_system_context(smm_dir: Path, stage: int) -> None:
    ctx = {"project_name": "test", "branching_strategy": {"stage": stage}}
    (smm_dir / "system_context.json").write_text(json.dumps(ctx))


def _make_plan(branch: str | None = None, milestones: list | None = None) -> dict:
    plan = {
        "title": "Capstone Test Plan",
        "sources": [],
        "overview": "ov",
        "milestones": milestones or [],
    }
    if branch is not None:
        plan["branch"] = branch
    return plan


def _milestone(number: int, status: str, delivered_sprint: str | None = None) -> dict:
    return {
        "number": number,
        "name": f"Milestone {number}",
        "status": status,
        "delivered_sprint": delivered_sprint,
        "goal": "g",
        "done": "d",
        "sources": "s",
        "change_zones": [],
        "impact_zones": [],
        "design_details": "dd",
        "constraints": [],
    }


class TestPlanBranchFlow(_IntegrationTestCase):
    """End-to-end exercise of plan-branch surfaces from stories 001 + 002."""

    def _plan_cli(self, *args, stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(_PLAN_CLI), "--smm-dir", str(self.smm_dir), *args],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            input=stdin,
            env=self._test_env,
        )

    def _branching(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(_BRANCHING), "--smm-dir", str(self.smm_dir), *args],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            env=self._test_env,
        )

    @staticmethod
    def _parse_branch(output: str) -> str:
        """Extract branch name from CLI output like 'created: X' or 'resumed: X'."""
        line = output.strip()
        for prefix in ("created: ", "resumed: "):
            if line.startswith(prefix):
                return line[len(prefix) :]
        return line

    def _create_plan_with_branch(self, branch: str) -> None:
        plan_json = json.dumps(_make_plan(branch=branch))
        result = self._plan_cli("create", stdin=plan_json)
        self.assertEqual(result.returncode, 0, result.stderr)

    # AC 1: plan_cli round-trips the branch field
    def test_plan_create_with_branch_then_get_branch(self):
        self._create_plan_with_branch("paulingalls/plan-test")
        result = self._plan_cli("get-branch")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "paulingalls/plan-test")

    # AC 2: branching create-plan creates the named branch in the repo
    def test_create_plan_branch_creates_real_branch(self):
        _write_system_context(self.smm_dir, stage=2)
        # Empty plan exists so create-plan can record into it
        plan_json = json.dumps(_make_plan())
        self._plan_cli("create", stdin=plan_json)

        result = self._branching(
            "create-plan", "--cwd", str(self.tmpdir), "--slug", "ac2-create"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        branch_name = self._parse_branch(result.stdout)

        # Verify the branch actually exists locally
        check = subprocess.run(
            ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
            cwd=self.tmpdir,
            capture_output=True,
        )
        self.assertEqual(check.returncode, 0)

        # And the branch was recorded back into execution_plan.json
        get = self._plan_cli("get-branch")
        self.assertEqual(get.stdout.strip(), branch_name)

    # AC 3: create-sprint forks off the plan branch when one exists
    def test_create_sprint_forks_off_plan_branch(self):
        _write_system_context(self.smm_dir, stage=2)
        # Plan branch already exists and is recorded
        plan_json = json.dumps(_make_plan())
        self._plan_cli("create", stdin=plan_json)
        plan_result = self._branching(
            "create-plan", "--cwd", str(self.tmpdir), "--slug", "ac3-sprint-base"
        )
        plan_branch = self._parse_branch(plan_result.stdout)
        plan_tip = subprocess.run(
            ["git", "rev-parse", plan_branch],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Seed sprint.json so create-sprint has somewhere to record branch_name
        sprint_json = {
            "sprint_id": "sprint-099",
            "goal": "Test capstone sprint",
            "started": "2026-04-24",
            "milestone": "Milestone 1",
            "stories": [],
        }
        sprint_cli = _PLUGIN_ROOT / "smm" / "sprint_cli.py"
        subprocess.run(
            ["python3", str(sprint_cli), "--smm-dir", str(self.smm_dir), "create"],
            cwd=self.tmpdir,
            input=json.dumps(sprint_json),
            capture_output=True,
            text=True,
            env=self._test_env,
            check=True,
        )

        # An arbitrary slug — the slug-bug fix means this still works
        sprint_result = self._branching(
            "create-sprint",
            "--cwd",
            str(self.tmpdir),
            "--sprint",
            "sprint-099",
            "--slug",
            "anything",
        )
        self.assertEqual(sprint_result.returncode, 0, sprint_result.stderr)
        sprint_branch = self._parse_branch(sprint_result.stdout)

        # The new sprint branch's parent commit should be the plan branch tip
        merge_base = subprocess.run(
            ["git", "merge-base", sprint_branch, plan_branch],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(merge_base, plan_tip)

    # AC 4: get-target returns the plan branch when set
    def test_get_target_returns_plan_branch_when_set(self):
        _write_system_context(self.smm_dir, stage=2)
        plan_json = json.dumps(_make_plan())
        self._plan_cli("create", stdin=plan_json)
        plan_result = self._branching(
            "create-plan", "--cwd", str(self.tmpdir), "--slug", "ac4-target"
        )
        plan_branch = self._parse_branch(plan_result.stdout)

        target = self._branching("get-target", "--cwd", str(self.tmpdir))
        self.assertEqual(target.returncode, 0)
        self.assertEqual(target.stdout.strip(), plan_branch)

    # AC 5: is-plan-complete behavior across status combinations
    def test_is_plan_complete_responds_correctly(self):
        # All delivered/deferred → exit 0
        plan_json = json.dumps(
            _make_plan(
                milestones=[
                    _milestone(1, "delivered", delivered_sprint="sprint-001"),
                    _milestone(2, "deferred"),
                ]
            )
        )
        self._plan_cli("create", stdin=plan_json)
        result = self._plan_cli("is-plan-complete")
        self.assertEqual(result.returncode, 0)

        # One planned milestone left → exit 1
        plan_json = json.dumps(
            _make_plan(
                milestones=[
                    _milestone(1, "delivered", delivered_sprint="sprint-001"),
                    _milestone(2, "planned"),
                ]
            )
        )
        self._plan_cli("create", stdin=plan_json)
        result = self._plan_cli("is-plan-complete")
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
