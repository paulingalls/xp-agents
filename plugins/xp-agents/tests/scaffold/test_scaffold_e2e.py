#!/usr/bin/env python3
"""Milestone-4 E2E for /xp-scaffold-acceptance Steps 6-9.

Drives the full CLI pipeline against a fixture repo + SMM at Stage 0
and asserts the [chore] commit, surface flip, and decision event all
land per doctrine.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _helpers import init_git_with_seed, run_git
from conftest import run_cli

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


def _setup_smm(smm_dir: Path) -> None:
    ctx = {
        "product": "Demo product.",
        "architecture_overview": "Simple frontend.",
        "stack": {"languages": ["TypeScript"]},
        "modules": [{"name": "app", "purpose": "App", "path": "src/app"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "lang", "decision": "Use TS"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
        "branching_strategy": {"stage": 0},
        "acceptance_surfaces": [
            {
                "name": "browser",
                "signals": ["next.js"],
                "harness": "playwright",
                "status": "gap",
            }
        ],
    }
    (smm_dir / "system_context.json").write_text(json.dumps(ctx), encoding="utf-8")


_PLAN_INPUT = {
    "surface": "browser",
    "tool": "playwright",
    "tool_version": "1.51.0",
    "files_to_create": [
        {
            "path": "tests/acceptance/example.spec.ts",
            "description": "happy",
            "body": "export default 1;\n",
        }
    ],
    "files_to_modify": [],
    "install_cmds": ["true"],
    "verify_cmd": "true",
    "branch_name": "paul/scaffold-browser-acceptance",
}


class TestScaffoldM4Pipeline(unittest.TestCase):
    """E2E: build-plan → apply-write → install → verify → commit → record.

    Pins the milestone-4 done-state for /xp-scaffold-acceptance: a
    Stage-0 run leaves a [chore] Scaffold commit on HEAD, the
    system_context surface flipped to covered with
    acceptance_template_command set, and (when --concern-id is
    supplied) a decision event resolving the missing-acceptance
    concern via metadata.resolves.
    """

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-e2e-repo-"))
        self.smm_dir = Path(tempfile.mkdtemp(prefix="scaffold-e2e-smm-"))
        init_git_with_seed(self.repo, "package.json", '{"name": "demo"}\n')
        _setup_smm(self.smm_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.smm_dir, ignore_errors=True)

    def _run(self, argv: list[str], stdin_data: str = "") -> dict:
        result = run_cli(_CLI, argv, self.smm_dir, stdin_data=stdin_data)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_full_pipeline_browser_stage_0(self) -> None:
        # build-plan and apply-write produce a snapshot the rest of the
        # pipeline drives off; install/verify exercise the M-3 phases.
        self._run(
            ["build-plan"], stdin_data=json.dumps(_PLAN_INPUT)
        )  # round-trips plan structure
        write_payload = self._run(
            ["apply-write", "--repo-root", str(self.repo)],
            stdin_data=json.dumps(_PLAN_INPUT),
        )
        snap_id = write_payload["snapshot_id"]
        self.addCleanup(
            shutil.rmtree, write_payload["snapshot_dir"], True
        )  # cleanup snap dir

        self._run(
            ["apply-install", "--snapshot-id", snap_id, "--repo-root", str(self.repo)]
        )
        self._run(
            ["apply-verify", "--snapshot-id", snap_id, "--repo-root", str(self.repo)]
        )

        commit_payload = self._run(
            [
                "apply-commit",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self.repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
                "--concern-id",
                "abc123def456",
            ]
        )
        self.assertTrue(commit_payload["ok"])
        self.assertEqual(commit_payload["branch"], "main")  # stage 0 → HEAD

        self._run(
            [
                "apply-record",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self.repo),
                "--surface",
                "browser",
                "--concern-id",
                "abc123def456",
                "--agent-id",
                "test-agent",
            ]
        )

        # Commit landed on HEAD with the doctrine subject + four trailers.
        body = run_git(["git", "log", "-1", "--format=%B"], self.repo).stdout
        self.assertIn(
            "[chore] Scaffold browser acceptance via playwright", body.splitlines()[0]
        )
        for trailer in (
            "Tool-version: 1.51.0",
            "Files-created: tests/acceptance/example.spec.ts",
            "Verification: true",
            "Resolves-Event: abc123def456",
        ):
            self.assertIn(trailer, body, f"missing trailer: {trailer!r}")

        # system_context flipped covered + template command stamped.
        ctx = json.loads(
            (self.smm_dir / "system_context.json").read_text(encoding="utf-8")
        )
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "covered")
        self.assertEqual(browser["acceptance_template_command"], "true")

        # Decision event with metadata.resolves landed.
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertTrue(decisions, "no decision event recorded")
        self.assertIn("abc123def456", decisions[-1].get("metadata", {}).get("resolves"))


if __name__ == "__main__":
    unittest.main()
