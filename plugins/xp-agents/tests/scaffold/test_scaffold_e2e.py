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

from _bases import _PLUGIN_ROOT
from _helpers import (
    init_git_with_seed,
    load_system_context,
    run_git,
    run_scaffold_pipeline,
    valid_system_context,
)
from conftest import run_cli
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_DECISION

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


def _setup_smm(smm_dir: Path) -> None:
    ctx = valid_system_context(
        surfaces=[
            {
                "name": "browser",
                "signals": ["next.js"],
                "harness": "playwright",
                "status": "gap",
            }
        ]
    )
    ctx["branching_strategy"] = {"stage": 0}
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
        commit_payload = run_scaffold_pipeline(
            self,
            self._run,
            self.repo,
            surface="browser",
            tool="playwright",
            plan=_PLAN_INPUT,
        )
        self.assertEqual(commit_payload["branch"], "main")  # stage 0 → HEAD
        commit_sha = commit_payload["sha"]
        snap_id = commit_payload["snapshot_id"]

        # Commit landed on HEAD with the doctrine subject + four trailers.
        body = run_git(["git", "log", "-1", "--format=%B"], self.repo).stdout
        self.assertIn(
            "[chore] Scaffold acceptance browser via playwright", body.splitlines()[0]
        )
        for trailer in (
            "Tool-version: 1.51.0",
            "Files-created: tests/acceptance/example.spec.ts",
            "Verification: true",
            "Resolves-Event: abc123def456",
        ):
            self.assertIn(trailer, body, f"missing trailer: {trailer!r}")

        # system_context flipped covered + template command stamped.
        ctx = load_system_context(self.smm_dir)
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
        decisions = events_of_type(events, EVENT_TYPE_DECISION)
        self.assertTrue(decisions, "no decision event recorded")
        decision_meta = decisions[-1].get("metadata", {})
        self.assertIn("abc123def456", decision_meta.get("resolves"))
        # Provenance: snapshot_id + commit_sha land on the decision event so
        # the surface flip can be cross-referenced back to the apply pipeline.
        self.assertEqual(decision_meta.get("snapshot_id"), snap_id)
        self.assertEqual(decision_meta.get("commit_sha"), commit_sha)


if __name__ == "__main__":
    unittest.main()
