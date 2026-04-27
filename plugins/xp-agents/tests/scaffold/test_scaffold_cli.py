#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — thin CLI wrapper over scaffold helpers.

Covers all five subcommands (teammates-active, detect-surfaces,
assess-tool, build-plan, render-preview) plus key error paths. Follows
the run_cli + _SMMTestCase pattern from tests/engine/test_plan_cli.py.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


def _valid_system_context(surfaces: list[dict] | None = None) -> dict:
    doc: dict = {
        "product": "A test product.",
        "architecture_overview": "Simple architecture.",
        "stack": {"languages": ["Python"]},
        "modules": [{"name": "core", "purpose": "Core logic", "path": "src/core"}],
        "conventions": ["Use type hints"],
        "key_decisions": [{"topic": "language", "decision": "Use Python"}],
        "sources": ["CLAUDE.md"],
        "project_specific": [],
    }
    if surfaces is not None:
        doc["acceptance_surfaces"] = surfaces
    return doc


class TestTeammatesActive(_SMMTestCase):
    def test_no_teammates_exits_zero(self) -> None:
        result = run_cli(
            _CLI,
            ["teammates-active", "--agent-id", "main"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_active_teammates_exits_one_with_json_payload(self) -> None:
        coord_path = self.smm_dir / ".coordination.json"
        coord_path.write_text(
            json.dumps(
                {
                    "paul": {
                        "updated": "2099-01-01T00:00:00+00:00",
                        "worktree": "story-001",
                    },
                    "alice": {
                        "updated": "2099-01-01T00:00:00+00:00",
                        "worktree": "story-002",
                    },
                }
            ),
            encoding="utf-8",
        )
        result = run_cli(
            _CLI,
            ["teammates-active", "--agent-id", "main"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            sorted(w["agent_id"] for w in payload["worktrees"]), ["alice", "paul"]
        )

    def test_missing_smm_dir_exits_two_not_one(self) -> None:
        """Exit 2 (not 1) when --smm-dir is missing, so the agent doesn't
        misfire the doctrine refusal on a misconfigured invocation."""
        cli = _CLI
        result = subprocess.run(
            [sys.executable, str(cli), "teammates-active", "--agent-id", "main"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--smm-dir", result.stderr)

    def test_excludes_self_from_count(self) -> None:
        coord_path = self.smm_dir / ".coordination.json"
        coord_path.write_text(
            json.dumps(
                {
                    "main": {
                        "updated": "2099-01-01T00:00:00+00:00",
                        "worktree": "self",
                    },
                }
            ),
            encoding="utf-8",
        )
        result = run_cli(
            _CLI,
            ["teammates-active", "--agent-id", "main"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0)


class TestDetectSurfaces(_SMMTestCase):
    def test_empty_smm_returns_empty_array(self) -> None:
        result = run_cli(
            _CLI,
            ["detect-surfaces", "--repo-root", str(self.smm_dir)],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [])

    def test_returns_surface_array(self) -> None:
        ctx = _valid_system_context(
            surfaces=[
                {
                    "name": "browser",
                    "signals": ["next.js"],
                    "harness": "playwright",
                    "status": "gap",
                },
            ]
        )
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(ctx), encoding="utf-8"
        )
        result = run_cli(
            _CLI,
            ["detect-surfaces", "--repo-root", str(self.smm_dir)],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0)
        surfaces = json.loads(result.stdout)
        self.assertEqual(len(surfaces), 1)
        self.assertEqual(surfaces[0]["name"], "browser")
        self.assertEqual(surfaces[0]["status"], "gap")
        self.assertIn("has_tooling", surfaces[0])


class TestAssessTool(_SMMTestCase):
    def test_empty_guidance_declines(self) -> None:
        result = run_cli(
            _CLI,
            ["assess-tool", "--tool", "obscure-runner"],
            self.smm_dir,
            stdin_data="",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["decline"])
        self.assertIn("obscure-runner", payload["reason"])

    def test_whitespace_only_guidance_declines(self) -> None:
        result = run_cli(
            _CLI,
            ["assess-tool", "--tool", "obscure-runner"],
            self.smm_dir,
            stdin_data="   \n  ",
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["decline"])

    def test_concrete_guidance_passes(self) -> None:
        result = run_cli(
            _CLI,
            ["assess-tool", "--tool", "playwright"],
            self.smm_dir,
            stdin_data="Install via npm install -D @playwright/test; configure...",
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["decline"])
        self.assertIsNone(payload["reason"])

    def test_guidance_with_shell_metachars_passes_safely(self) -> None:
        """The whole reason for the CLI refactor: guidance with quotes,
        backslashes, $vars, and triple-quotes must NOT break the call."""
        nasty = (
            "Install: npm install --save-dev '''@scope/runner''' "
            '&& echo "$DONE"\nNewline + tab\there\\with\\backslashes'
        )
        result = run_cli(
            _CLI,
            ["assess-tool", "--tool", "@scope/runner"],
            self.smm_dir,
            stdin_data=nasty,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["decline"])


class TestBuildPlan(_SMMTestCase):
    def _valid_input(self, **overrides) -> dict:
        data = {
            "surface": "browser",
            "tool": "playwright",
            "tool_version": "1.51.0",
            "files_to_create": [
                {
                    "path": "tests/acceptance/example.spec.ts",
                    "description": "happy-path test",
                    "line_count": 12,
                },
            ],
            "files_to_modify": [
                {"path": ".gitignore", "description": "+1 line"},
            ],
            "install_cmds": ["npm install"],
            "verify_cmd": "npx playwright test",
            "branch_name": "paul/scaffold-browser-acceptance",
        }
        data.update(overrides)
        return data

    def test_valid_input_returns_scaffold_plan(self) -> None:
        result = run_cli(
            _CLI,
            ["build-plan"],
            self.smm_dir,
            stdin_data=json.dumps(self._valid_input()),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        for key in (
            "surface",
            "tool",
            "tool_version",
            "files_to_create",
            "files_to_modify",
            "install_cmds",
            "verify_cmd",
            "branch_name",
            "commit_msg",
        ):
            self.assertIn(key, plan)
        self.assertEqual(plan["surface"], "browser")
        self.assertIn("playwright", plan["commit_msg"])
        self.assertIn("1.51.0", plan["commit_msg"])

    def test_invalid_json_exits_one(self) -> None:
        result = run_cli(
            _CLI,
            ["build-plan"],
            self.smm_dir,
            stdin_data="not json {",
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())

    def test_missing_required_field_exits_one(self) -> None:
        bad = self._valid_input()
        del bad["surface"]
        result = run_cli(
            _CLI,
            ["build-plan"],
            self.smm_dir,
            stdin_data=json.dumps(bad),
        )
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.strip())


class TestRenderPreview(_SMMTestCase):
    def _sample_plan(self) -> dict:
        build_input = {
            "surface": "browser",
            "tool": "playwright",
            "tool_version": "1.51.0",
            "files_to_create": [
                {
                    "path": "tests/acceptance/example.spec.ts",
                    "description": "happy-path test",
                    "line_count": 12,
                },
            ],
            "files_to_modify": [
                {"path": ".gitignore", "description": "+1 line"},
            ],
            "install_cmds": ["npm install"],
            "verify_cmd": "npx playwright test",
            "branch_name": "paul/scaffold-browser-acceptance",
        }
        result = run_cli(
            _CLI,
            ["build-plan"],
            self.smm_dir,
            stdin_data=json.dumps(build_input),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_renders_preview_with_doctrine_sections(self) -> None:
        plan = self._sample_plan()
        result = run_cli(
            _CLI,
            ["render-preview"],
            self.smm_dir,
            stdin_data=json.dumps(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for marker in (
            "Selected surface",
            "Selected tool",
            "Planning scaffold",
            "Install + verify",
            "Commit plan",
        ):
            self.assertIn(marker, result.stdout)

    def test_preview_ends_with_proceed_prompt(self) -> None:
        plan = self._sample_plan()
        result = run_cli(
            _CLI,
            ["render-preview"],
            self.smm_dir,
            stdin_data=json.dumps(plan),
        )
        self.assertTrue(
            result.stdout.rstrip().endswith("Proceed? [yes / show files / no]"),
            f"Tail: {result.stdout.rstrip()[-80:]!r}",
        )

    def test_invalid_json_exits_one(self) -> None:
        result = run_cli(
            _CLI,
            ["render-preview"],
            self.smm_dir,
            stdin_data="not json",
        )
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
