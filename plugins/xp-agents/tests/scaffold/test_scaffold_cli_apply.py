#!/usr/bin/env python3
"""Tests for scripts/scaffold_cli.py — apply lifecycle subcommands.

Covers: apply-write, apply-install, apply-verify, apply-revert. The
shared _ApplyCliTestBase fixture (originally defined here) now lives
in `_scaffold_cli_apply_helpers.py` (split out when this file grew
past the 500-line cap) and is re-used by the apply-commit sibling
(test_scaffold_cli_apply_commit.py) and by the record-test sibling
file (test_scaffold_cli_record.py).
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _bases import _PLUGIN_ROOT
from _scaffold_cli_apply_helpers import _ApplyCliTestBase
from conftest import run_cli

_CLI = _PLUGIN_ROOT / "scripts" / "scaffold_cli.py"


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


if __name__ == "__main__":
    unittest.main()
