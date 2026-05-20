#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — apply lifecycle subcommands.

Covers: apply-write, apply-install, apply-verify, apply-revert,
apply-commit (stage-0 and stage-2 protected). The shared
_ApplyCliTestBase fixture is defined here and re-used by the record-test
sibling file (test_scaffold_cli_record.py).
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _helpers import init_git_identity, run_git
from conftest import _SMMTestCase, run_cli

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


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


class TestApplyRequiresRepoRoot(_ApplyCliTestBase):
    """apply-install / apply-verify / apply-revert require --repo-root.

    Concern 0a6e983fd1d4 (--repo-root contract). Previously these three
    subcommands defaulted --repo-root to Path.cwd() while apply-write,
    apply-commit, apply-record, and the detect-* subcommands were
    required=True. The mixed contract risked silent surprise when a
    caller invoked from an unexpected cwd. Pin "required everywhere".
    """

    def test_apply_install_requires_repo_root(self) -> None:
        result = run_cli(
            _CLI,
            ["apply-install", "--snapshot-id", "abc"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--repo-root", result.stderr)

    def test_apply_verify_requires_repo_root(self) -> None:
        result = run_cli(
            _CLI,
            ["apply-verify", "--snapshot-id", "abc"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--repo-root", result.stderr)

    def test_apply_revert_requires_repo_root(self) -> None:
        result = run_cli(
            _CLI,
            ["apply-revert", "--snapshot-id", "abc"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--repo-root", result.stderr)


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


class TestApplyCommitStageTwoOnProtectedBase(_ApplyCliCommitTestBase):
    stage = 2

    def test_forks_child_off_main_at_stage_2(self) -> None:
        """On main (protected) at stage 2, apply-commit forks the scaffold
        child off main and commits there instead of refusing — branching off
        a protected base is fine; the child keeps the commit off main."""
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
        self.assertTrue(payload["ok"], payload.get("reason"))
        self.assertTrue(payload["branch"].endswith("/scaffold"))

    def test_refuses_on_story_branch_at_stage_2(self) -> None:
        """apply-commit on a story branch surfaces commit_scaffold's refusal
        as an ok=False payload with guidance to the sprint branch."""
        run_git(["git", "checkout", "-b", "paulingalls/story-007-x"], self._repo)
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
        reason = payload["reason"].lower()
        self.assertIn("story", reason)
        self.assertIn("sprint", reason)


if __name__ == "__main__":
    unittest.main()
