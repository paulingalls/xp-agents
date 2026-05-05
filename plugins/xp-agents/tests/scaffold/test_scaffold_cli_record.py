#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — apply-record subcommand.

Reuses _ApplyCliTestBase from test_scaffold_cli_apply (the base class
sets up the temp repo + apply-write pipeline). Record-specific fixture
adds a system_context with a 'gap' surface and seeds a Scaffold commit.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _helpers import init_git_identity, run_git, valid_system_context
from conftest import run_cli
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_DECISION
from test_scaffold_cli_apply import _ApplyCliTestBase

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


class _ApplyCliRecordTestBase(_ApplyCliTestBase):
    """_ApplyCliTestBase + system_context.json with browser:gap surface +
    a seeded ``[chore] Scaffold ...`` commit at HEAD.

    apply-record now requires ``--commit-sha`` (atomicity gate); the seeded
    commit's sha is exposed via ``self._scaffold_sha`` so happy-path tests
    can pass a valid sha without driving the full apply-commit pipeline.
    Stage 0 since record is unaffected by branching stage.
    """

    def setUp(self) -> None:
        super().setUp()
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
        (self.smm_dir / "system_context.json").write_text(
            json.dumps(ctx), encoding="utf-8"
        )
        init_git_identity(self._repo)
        run_git(["git", "add", "package.json"], self._repo)
        scaffold_subject = "[chore] Scaffold acceptance browser via playwright"
        run_git(["git", "commit", "-m", scaffold_subject], self._repo)
        self._scaffold_sha = run_git(
            ["git", "rev-parse", "HEAD"], self._repo
        ).stdout.strip()


class TestApplyRecord(_ApplyCliRecordTestBase):
    def test_happy_path_flips_surface_and_returns_ok(self) -> None:
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-record",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--agent-id",
                "test-agent",
                "--commit-sha",
                self._scaffold_sha,
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        ctx = json.loads(
            (self.smm_dir / "system_context.json").read_text(encoding="utf-8")
        )
        browser = next(s for s in ctx["acceptance_surfaces"] if s["name"] == "browser")
        self.assertEqual(browser["status"], "covered")
        self.assertEqual(browser["acceptance_template_command"], "true")

    def test_concern_id_appends_decision_event(self) -> None:
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-record",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--concern-id",
                "abc123def456",
                "--agent-id",
                "test-agent",
                "--commit-sha",
                self._scaffold_sha,
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["decision_event_id"])
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        decisions = events_of_type(events, EVENT_TYPE_DECISION)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(
            decisions[0].get("metadata", {}).get("resolves"), ["abc123def456"]
        )


if __name__ == "__main__":
    unittest.main()
