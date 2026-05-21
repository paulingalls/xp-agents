#!/usr/bin/env python3
"""Milestone-1 capstone E2E for /xp-scaffold-acceptance.

Pins the M-1 done-criterion (execution_plan.json §Milestone 1): "Running
/xp-scaffold-acceptance on a project with N uncovered surfaces produces N
commits and flips all to covered in one invocation." Where
test_scaffold_skill_multi_surface.py asserts the SKILL.md *prose* of the
multi-surface loop, this exercises the loop's runtime by driving
scaffold_cli.py through the SKILL's per-surface phase commands
(list-uncovered → per surface apply-write/install/verify/commit/record).
The SKILL's optional apply-verify-identity phase is a no-op for these
fixtures (no verify_identity_cmd set), so it is elided.

Stories 001-004 are already done, so these tests pass on first write — the
"red" they guard against is an import break or a regression in the shipped
pipeline, not a red→green production cycle.

Stage 0 (branching_strategy.stage == 0) keeps both surface commits on the
temp repo's current branch, so git log shows exactly N scaffold commits on
one branch. Per-surface sequencing (the full phase block runs to completion
for one surface before the next starts) is load-bearing: record_scaffold's
HEAD-advancement gate refuses if HEAD has moved past the scaffold commit, so
a "commit all, then record all" reordering would break surface 1's record.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _bases import _PLUGIN_ROOT
from _helpers import (
    init_git_with_seed,
    load_system_context,
    run_git,
    run_scaffold_pipeline,
    valid_system_context,
)
from conftest import run_cli
from scaffold_post import SCAFFOLD_COMMIT_PREFIX

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"

_DUMMY_CONCERN = "abc123def456"

_CLI_PLAN = {
    "surface": "cli",
    "tool": "bats",
    "tool_version": "1.11.0",
    "files_to_create": [
        {
            "path": "tests/acceptance/cli.bats",
            "description": "cli happy path",
            "body": "@test 'noop' { true; }\n",
        }
    ],
    "files_to_modify": [],
    "install_cmds": ["true"],
    "verify_cmd": "true",
}

_BROWSER_PLAN = {
    "surface": "browser",
    "tool": "playwright",
    "tool_version": "1.51.0",
    "files_to_create": [
        {
            "path": "tests/acceptance/browser.spec.ts",
            "description": "browser happy path",
            "body": "export default 1;\n",
        }
    ],
    "files_to_modify": [],
    "install_cmds": ["true"],
    "verify_cmd": "true",
}


class TestMultiSurfaceLoopE2E(unittest.TestCase):
    """Capstone: N uncovered surfaces → N commits → N covered, one invocation."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-m1-repo-"))
        self.smm_dir = Path(tempfile.mkdtemp(prefix="scaffold-m1-smm-"))
        init_git_with_seed(self.repo, "README.md", "# seed\n")
        ctx = valid_system_context(
            surfaces=[
                {"name": "cli", "signals": ["argv"], "status": "gap"},
                {"name": "browser", "signals": ["next.js"], "status": "gap"},
            ]
        )
        ctx["branching_strategy"] = {"stage": 0}
        (self.smm_dir / "system_context.json").write_text(
            json.dumps(ctx), encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.smm_dir, ignore_errors=True)

    def _run(self, argv: list[str], stdin_data: str = "") -> Any:
        result = run_cli(_CLI, argv, self.smm_dir, stdin_data=stdin_data)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def _list_uncovered(self) -> list[dict]:
        return self._run(["list-uncovered", "--repo-root", str(self.repo)])

    def _load_ctx(self) -> dict:
        return load_system_context(self.smm_dir)

    def _scaffold_subjects(self) -> list[str]:
        out = run_git(["git", "log", "--format=%s"], self.repo).stdout
        return [s for s in out.splitlines() if s.startswith(SCAFFOLD_COMMIT_PREFIX)]

    def _scaffold_one(self, surface: str, tool: str, plan: dict) -> str:
        """Run the SKILL loop body for one surface; return the commit sha."""
        commit = run_scaffold_pipeline(
            self,
            self._run,
            self.repo,
            surface=surface,
            tool=tool,
            plan=plan,
            concern_id=_DUMMY_CONCERN,
        )
        return commit["sha"]

    def test_two_uncovered_produce_two_commits_and_flip_covered(self) -> None:
        """AC1+AC2: both gap surfaces scaffold to exactly 2 commits, both covered."""
        names = {e["name"] for e in self._list_uncovered()}
        self.assertEqual(names, {"cli", "browser"})

        self._scaffold_one("cli", "bats", _CLI_PLAN)
        self._scaffold_one("browser", "playwright", _BROWSER_PLAN)

        self.assertEqual(len(self._scaffold_subjects()), 2)

        surfaces = {s["name"]: s for s in self._load_ctx()["acceptance_surfaces"]}
        for name in ("cli", "browser"):
            self.assertEqual(surfaces[name]["status"], "covered")
            self.assertEqual(surfaces[name]["acceptance_template_command"], "true")

    def test_partial_rerun_skips_covered_surface(self) -> None:
        """AC3: with cli already covered, a re-run scaffolds only browser."""
        self._scaffold_one("cli", "bats", _CLI_PLAN)
        before = len(self._scaffold_subjects())
        self.assertEqual(before, 1)

        # list-uncovered drops the covered surface — the loop never revisits it.
        self.assertEqual([e["name"] for e in self._list_uncovered()], ["browser"])

        self._scaffold_one("browser", "playwright", _BROWSER_PLAN)
        self.assertEqual(len(self._scaffold_subjects()), before + 1)

        surfaces = {s["name"]: s for s in self._load_ctx()["acceptance_surfaces"]}
        self.assertEqual(surfaces["cli"]["status"], "covered")
        self.assertEqual(surfaces["cli"]["acceptance_template_command"], "true")
        self.assertEqual(surfaces["browser"]["status"], "covered")


class TestMultiSurfaceLoopStage2E2E(unittest.TestCase):
    """Stage-2: all surfaces land on ONE shared scaffold branch forked off the
    sprint branch — not a per-surface branch chained off the previous surface
    (decision 664fdaee5954, resolves dda49fa03342)."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-s2-repo-"))
        self.smm_dir = Path(tempfile.mkdtemp(prefix="scaffold-s2-smm-"))
        init_git_with_seed(self.repo, "README.md", "# seed\n")
        # A sprint branch is the current branch; the scaffold branch must
        # fork off it (its tip stays reachable from the shared branch).
        run_git(["git", "checkout", "-b", "test/sprint-089-x"], self.repo)
        (self.repo / "sprint.txt").write_text("sprint\n", encoding="utf-8")
        run_git(["git", "add", "sprint.txt"], self.repo)
        run_git(["git", "commit", "-m", "sprint work"], self.repo)
        self.sprint_tip = run_git(
            ["git", "rev-parse", "HEAD"], self.repo
        ).stdout.strip()
        ctx = valid_system_context(
            surfaces=[
                {"name": "cli", "signals": ["argv"], "status": "gap"},
                {"name": "browser", "signals": ["next.js"], "status": "gap"},
            ]
        )
        ctx["branching_strategy"] = {"stage": 2}
        (self.smm_dir / "system_context.json").write_text(
            json.dumps(ctx), encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.smm_dir, ignore_errors=True)

    def _run(self, argv: list[str], stdin_data: str = "") -> Any:
        result = run_cli(_CLI, argv, self.smm_dir, stdin_data=stdin_data)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def _branches(self) -> list[str]:
        out = run_git(["git", "branch", "--format=%(refname:short)"], self.repo).stdout
        return [b.strip() for b in out.splitlines() if b.strip()]

    def _commits_on(self, branch: str) -> set[str]:
        out = run_git(["git", "log", "--format=%H", branch], self.repo).stdout
        return {ln for ln in out.splitlines() if ln}

    def _scaffold_subjects_on(self, branch: str) -> list[str]:
        out = run_git(["git", "log", "--format=%s", branch], self.repo).stdout
        return [s for s in out.splitlines() if s.startswith(SCAFFOLD_COMMIT_PREFIX)]

    def test_surfaces_share_one_branch_forked_off_sprint(self) -> None:
        cli_commit = run_scaffold_pipeline(
            self, self._run, self.repo, surface="cli", tool="bats", plan=_CLI_PLAN
        )
        browser_commit = run_scaffold_pipeline(
            self,
            self._run,
            self.repo,
            surface="browser",
            tool="playwright",
            plan=_BROWSER_PLAN,
        )

        # Both surfaces report the same shared scaffold branch.
        self.assertTrue(cli_commit["branch"].endswith("/scaffold"))
        self.assertEqual(cli_commit["branch"], browser_commit["branch"])
        shared = cli_commit["branch"]

        # Exactly one scaffold branch; no per-surface branch was chained.
        scaffold_branches = [b for b in self._branches() if b.endswith("/scaffold")]
        self.assertEqual(scaffold_branches, [shared])
        self.assertEqual(
            [b for b in self._branches() if "/scaffold-" in b],
            [],
            "a per-surface scaffold branch was chained — should be one shared branch",
        )

        # Forked off the sprint branch (its tip stays reachable) and carries
        # both surface commits.
        reachable = self._commits_on(shared)
        self.assertIn(self.sprint_tip, reachable)
        self.assertEqual(len(self._scaffold_subjects_on(shared)), 2)

    def test_partial_rerun_resumes_same_branch_off_sprint(self) -> None:
        """AC: a partial prior run resumes the existing shared branch (not a
        duplicate) AND the resumed branch still descends from the sprint
        branch, not a stale base."""
        first = run_scaffold_pipeline(
            self, self._run, self.repo, surface="cli", tool="bats", plan=_CLI_PLAN
        )
        # list-uncovered drops the now-covered cli surface.
        uncovered = [
            e["name"]
            for e in self._run(["list-uncovered", "--repo-root", str(self.repo)])
        ]
        self.assertEqual(uncovered, ["browser"])

        second = run_scaffold_pipeline(
            self,
            self._run,
            self.repo,
            surface="browser",
            tool="playwright",
            plan=_BROWSER_PLAN,
        )
        self.assertEqual(first["branch"], second["branch"])
        self.assertEqual(
            len([b for b in self._branches() if b.endswith("/scaffold")]), 1
        )
        self.assertIn(self.sprint_tip, self._commits_on(second["branch"]))


if __name__ == "__main__":
    unittest.main()
