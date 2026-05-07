#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — detection/planning/preview subcommands.

Covers: teammates-active, detect-surfaces, assess-tool, build-plan,
render-preview (with --show-files), plus surface-detection helpers.
Apply lifecycle and record subcommands are split into sibling files.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _helpers import init_git_identity, run_git, valid_system_context
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


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
        ctx = valid_system_context(
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


class TestFindIntroducingCommit(_SMMTestCase):
    """SKILL.md Step 1c redo branch invokes this to pin the revert pointer."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.smm_dir / "repo"
        self.repo.mkdir()
        init_git_identity(self.repo)

    def _commit(self, filename: str, body: str, message: str) -> None:
        (self.repo / filename).write_text(body, encoding="utf-8")
        run_git(["git", "add", filename], self.repo)
        run_git(["git", "commit", "-m", message], self.repo)

    def test_returns_introducing_commit_json(self) -> None:
        self._commit("README.md", "seed\n", "first")
        self._commit("playwright.config.ts", "{}\n", "add playwright")

        result = run_cli(
            _CLI,
            [
                "find-introducing-commit",
                "--repo-root",
                str(self.repo),
                "--config-files",
                str(self.repo / "playwright.config.ts"),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["subject"], "add playwright")
        self.assertIn("sha", payload)
        self.assertIn("date", payload)

    def test_returns_null_when_untracked(self) -> None:
        self._commit("README.md", "seed\n", "first")
        (self.repo / "untracked.config").write_text("{}\n", encoding="utf-8")

        result = run_cli(
            _CLI,
            [
                "find-introducing-commit",
                "--repo-root",
                str(self.repo),
                "--config-files",
                str(self.repo / "untracked.config"),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout))


class TestDetectMonorepo(_SMMTestCase):
    """SKILL.md Step 1d invokes this to ask the customer where to scaffold."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.smm_dir / "repo"
        self.repo.mkdir()

    def test_returns_no_signal_for_single_package(self) -> None:
        (self.repo / "package.json").write_text('{"name":"x"}', encoding="utf-8")

        result = run_cli(
            _CLI,
            ["detect-monorepo", "--repo-root", str(self.repo)],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["is_monorepo"])
        self.assertIsNone(payload["kind"])
        self.assertEqual(payload["packages"], [])

    def test_returns_pnpm_kind_with_packages(self) -> None:
        (self.repo / "pnpm-workspace.yaml").write_text(
            'packages:\n  - "packages/*"\n', encoding="utf-8"
        )
        (self.repo / "packages").mkdir()
        (self.repo / "packages" / "web").mkdir()
        (self.repo / "packages" / "api").mkdir()

        result = run_cli(
            _CLI,
            ["detect-monorepo", "--repo-root", str(self.repo)],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["is_monorepo"])
        self.assertEqual(payload["kind"], "pnpm")
        self.assertIn("packages/web", payload["packages"])
        self.assertIn("packages/api", payload["packages"])


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
        ):
            self.assertIn(key, plan)
        self.assertEqual(plan["surface"], "browser")

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
            "Commit branch",
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

    def test_show_files_renders_files_section(self) -> None:
        plan = self._sample_plan()
        plan["files_to_create"][0]["body"] = "test('x', () => {});\n"
        result = run_cli(
            _CLI,
            ["render-preview", "--show-files"],
            self.smm_dir,
            stdin_data=json.dumps(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Files:", result.stdout)
        self.assertIn("test('x', () => {});", result.stdout)

    def test_show_files_default_false(self) -> None:
        plan = self._sample_plan()
        plan["files_to_create"][0]["body"] = "test('x', () => {});\n"
        result = run_cli(
            _CLI,
            ["render-preview"],
            self.smm_dir,
            stdin_data=json.dumps(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Files:", result.stdout)


if __name__ == "__main__":
    unittest.main()
