#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — thin CLI wrapper over scaffold helpers.

Covers eleven subcommands: teammates-active, detect-surfaces, assess-tool,
build-plan, render-preview (with --show-files), apply-write,
apply-install, apply-verify, apply-revert, apply-commit, apply-record —
plus key error paths. Follows the run_cli + _SMMTestCase pattern from
tests/engine/test_plan_cli.py.
"""

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _helpers import init_git_identity, run_git, valid_system_context
from conftest import _SMMTestCase, run_cli
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
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


class _ApplyCliTestBase(_SMMTestCase):
    """Stages a temp repo + apply plan; runs apply-write to produce a snapshot."""

    def setUp(self) -> None:
        super().setUp()
        self._repo = self.smm_dir.parent / f"{self.smm_dir.name}-repo"
        self._repo.mkdir()
        (self._repo / "package.json").write_text('{"name": "demo"}\n', encoding="utf-8")
        self._snapshots: list[Path] = []

    def tearDown(self) -> None:
        for snap in self._snapshots:
            shutil.rmtree(snap, ignore_errors=True)
        shutil.rmtree(self._repo, ignore_errors=True)
        super().tearDown()

    def _track_snapshot(self, payload: dict) -> None:
        snap_dir = payload.get("snapshot_dir")
        if snap_dir:
            self._snapshots.append(Path(snap_dir))

    def _plan(self, **overrides: object) -> dict:
        plan = {
            "surface": "browser",
            "tool": "playwright",
            "tool_version": "1.51.0",
            "files_to_create": [
                {
                    "path": "tests/x.spec.ts",
                    "description": "happy",
                    "body": "x\n",
                }
            ],
            "files_to_modify": [
                {
                    "path": "package.json",
                    "description": "+dep",
                    "body": '{"name": "demo", "added": true}\n',
                }
            ],
            "install_cmds": ["true"],
            "verify_cmd": "true",
            "branch_name": "paul/scaffold-browser-acceptance",
        }
        plan.update(overrides)
        return plan

    def _apply_write(self, plan: dict) -> dict:
        result = run_cli(
            _CLI,
            ["apply-write", "--repo-root", str(self._repo)],
            self.smm_dir,
            stdin_data=json.dumps(plan),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self._track_snapshot(payload)
        return payload


class TestApplyWrite(_ApplyCliTestBase):
    def test_happy_path_returns_ok_with_snapshot_id(self) -> None:
        payload = self._apply_write(self._plan())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["snapshot_id"])
        self.assertTrue(Path(payload["snapshot_dir"]).exists())

    def test_files_actually_written(self) -> None:
        self._apply_write(self._plan())
        self.assertTrue((self._repo / "tests/x.spec.ts").exists())
        self.assertIn(
            '"added": true',
            (self._repo / "package.json").read_text(),
        )

    def test_invalid_json_stdin_exits_one(self) -> None:
        result = run_cli(
            _CLI,
            ["apply-write", "--repo-root", str(self._repo)],
            self.smm_dir,
            stdin_data="not json",
        )
        self.assertEqual(result.returncode, 1)


class TestApplyInstall(_ApplyCliTestBase):
    def test_happy_path_returns_ok(self) -> None:
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-install",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])

    def test_failure_reverts_and_records_phase(self) -> None:
        write_payload = self._apply_write(self._plan(install_cmds=["false"]))
        result = run_cli(
            _CLI,
            [
                "apply-install",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["phase"], "install")
        self.assertTrue(payload["reverted"])
        self.assertFalse((self._repo / "tests/x.spec.ts").exists())
        self.assertEqual(
            (self._repo / "package.json").read_text(),
            '{"name": "demo"}\n',
        )

    def test_missing_snapshot_id_exits_two(self) -> None:
        result = run_cli(
            _CLI,
            ["apply-install", "--snapshot-id", "nonexistent12"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)


class TestApplyVerify(_ApplyCliTestBase):
    def test_happy_path_returns_ok(self) -> None:
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-verify",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])

    def test_failure_reverts_and_records_phase(self) -> None:
        write_payload = self._apply_write(self._plan(verify_cmd="false"))
        result = run_cli(
            _CLI,
            [
                "apply-verify",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["phase"], "verify")
        self.assertTrue(payload["reverted"])


class TestApplyRevert(_ApplyCliTestBase):
    def test_explicit_cancel_after_write(self) -> None:
        write_payload = self._apply_write(self._plan())
        self.assertTrue((self._repo / "tests/x.spec.ts").exists())
        result = run_cli(
            _CLI,
            [
                "apply-revert",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["unrestored"], [])
        self.assertFalse((self._repo / "tests/x.spec.ts").exists())
        self.assertEqual(
            (self._repo / "package.json").read_text(),
            '{"name": "demo"}\n',
        )

    def test_missing_snapshot_id_exits_two(self) -> None:
        result = run_cli(
            _CLI,
            ["apply-revert", "--snapshot-id", "nonexistent12"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)


class TestApplyCliSnapshotLifecycle(_ApplyCliTestBase):
    """Snapshot dir lifecycle for the CLI split:
    - apply-write success: snapshot retained (next phase needs it)
    - apply-install success: snapshot retained (verify still needs it)
    - apply-verify success: snapshot retained (M-4 commit + record still need it)
    - apply-revert with unrestored=[]: cleaned up (explicit cancel)
    - any phase failure with clean revert: cleaned up by failure_result
    """

    def test_apply_install_success_retains_snapshot(self) -> None:
        write_payload = self._apply_write(self._plan())
        snap_id = write_payload["snapshot_id"]
        result = run_cli(
            _CLI,
            [
                "apply-install",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot_dir = Path(write_payload["snapshot_dir"])
        self.assertTrue(snapshot_dir.exists())

    def test_apply_verify_success_retains_snapshot(self) -> None:
        # M-4: apply-verify is no longer terminal — apply-commit + apply-record
        # both load the snapshot afterward, so cleanup moved from verify to
        # record (terminal in M-4) and explicit revert (terminal in cancel).
        write_payload = self._apply_write(self._plan())
        snap_id = write_payload["snapshot_id"]
        snapshot_dir = Path(write_payload["snapshot_dir"])
        result = run_cli(
            _CLI,
            [
                "apply-verify",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(snapshot_dir.exists())

    def test_apply_revert_after_apply_verify_succeeds(self) -> None:
        # M-4: apply-verify retains the snapshot, so a subsequent apply-revert
        # (the explicit-cancel terminal) finds it and cleans up cleanly.
        write_payload = self._apply_write(self._plan())
        snap_id = write_payload["snapshot_id"]
        snapshot_dir = Path(write_payload["snapshot_dir"])
        run_cli(
            _CLI,
            [
                "apply-verify",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        result = run_cli(
            _CLI,
            [
                "apply-revert",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(snapshot_dir.exists())

    def test_apply_revert_clean_cleans_up_snapshot(self) -> None:
        write_payload = self._apply_write(self._plan())
        snap_id = write_payload["snapshot_id"]
        snapshot_dir = Path(write_payload["snapshot_dir"])
        result = run_cli(
            _CLI,
            [
                "apply-revert",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertFalse(snapshot_dir.exists())

    def test_apply_install_failure_retains_snapshot_for_log_inspection(
        self,
    ) -> None:
        """Phase failure (clean revert) retains the snapshot so the log file
        named in `reason` survives for customer inspection."""
        write_payload = self._apply_write(self._plan(install_cmds=["false"]))
        snap_id = write_payload["snapshot_id"]
        snapshot_dir = Path(write_payload["snapshot_dir"])
        result = run_cli(
            _CLI,
            [
                "apply-install",
                "--snapshot-id",
                snap_id,
                "--repo-root",
                str(self._repo),
            ],
            self.smm_dir,
        )
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["unrestored"], [])
        self.assertTrue(snapshot_dir.exists())
        self.assertTrue((snapshot_dir / "install.log").exists())


class _ApplyCliCommitTestBase(_ApplyCliTestBase):
    """_ApplyCliTestBase + git init + identity + initial commit + stage config.

    Sets up a real git tempdir so apply-commit can actually run git.
    Subclasses override the ``stage`` class attribute for Stage 1+ tests.
    """

    stage: int = 0

    def setUp(self) -> None:
        super().setUp()
        init_git_identity(self._repo)
        run_git(["git", "add", "package.json"], self._repo)
        run_git(["git", "commit", "-m", "[chore] seed"], self._repo)
        (self.smm_dir / "system_context.json").write_text(
            json.dumps({"branching_strategy": {"stage": self.stage}}),
            encoding="utf-8",
        )


class TestApplyCommitStageZero(_ApplyCliCommitTestBase):
    def test_happy_path_returns_ok_with_sha_and_branch(self) -> None:
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-commit",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["sha"])
        self.assertEqual(payload["branch"], "main")

    def test_concern_id_in_resolves_event_trailer(self) -> None:
        write_payload = self._apply_write(self._plan())
        run_cli(
            _CLI,
            [
                "apply-commit",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
                "--concern-id",
                "abc123def456",
            ],
            self.smm_dir,
        )
        body = run_git(["git", "log", "-1", "--format=%B"], self._repo).stdout
        self.assertIn("Resolves-Event: abc123def456", body)


class TestApplyCommitStageOneProtected(_ApplyCliCommitTestBase):
    stage = 1

    def test_refuses_on_main_at_stage_1(self) -> None:
        write_payload = self._apply_write(self._plan())
        result = run_cli(
            _CLI,
            [
                "apply-commit",
                "--snapshot-id",
                write_payload["snapshot_id"],
                "--repo-root",
                str(self._repo),
                "--surface",
                "browser",
                "--tool",
                "playwright",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("main", payload["reason"])


class _ApplyCliRecordTestBase(_ApplyCliTestBase):
    """_ApplyCliTestBase + system_context.json with browser:gap surface.

    apply-record needs an existing surface to flip. Sets stage 0 since
    record is unaffected by branching stage.
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
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(
            decisions[0].get("metadata", {}).get("resolves"), ["abc123def456"]
        )


if __name__ == "__main__":
    unittest.main()
