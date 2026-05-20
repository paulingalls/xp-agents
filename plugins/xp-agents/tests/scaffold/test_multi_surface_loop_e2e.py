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
from _helpers import init_git_with_seed, run_git, valid_system_context
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
        return json.loads(
            (self.smm_dir / "system_context.json").read_text(encoding="utf-8")
        )

    def _scaffold_subjects(self) -> list[str]:
        out = run_git(["git", "log", "--format=%s"], self.repo).stdout
        return [s for s in out.splitlines() if s.startswith(SCAFFOLD_COMMIT_PREFIX)]

    def _scaffold_one(self, surface: str, tool: str, plan: dict) -> str:
        """Run the SKILL loop body for one surface; return the commit sha."""
        write = self._run(
            ["apply-write", "--repo-root", str(self.repo)],
            stdin_data=json.dumps(plan),
        )
        snap_id = write["snapshot_id"]
        self.addCleanup(shutil.rmtree, write["snapshot_dir"], True)

        repo = str(self.repo)
        self._run(["apply-install", "--snapshot-id", snap_id, "--repo-root", repo])
        self._run(["apply-verify", "--snapshot-id", snap_id, "--repo-root", repo])
        commit = self._run(
            [
                "apply-commit",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                repo,
                "--surface",
                surface,
                "--tool",
                tool,
                "--concern-id",
                _DUMMY_CONCERN,
            ]
        )
        self.assertTrue(commit["ok"], commit.get("reason"))
        self._run(
            [
                "apply-record",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                repo,
                "--surface",
                surface,
                "--concern-id",
                _DUMMY_CONCERN,
                "--agent-id",
                "test-agent",
                "--commit-sha",
                commit["sha"],
            ]
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


if __name__ == "__main__":
    unittest.main()
