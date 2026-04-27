#!/usr/bin/env python3
"""Tests for scaffold_apply.py — write/install/verify/atomic-revert pipeline."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from scaffold_apply import (
    ApplyResult,
    apply_plan,
)


def _plan(
    *,
    files_to_create: list | None = None,
    files_to_modify: list | None = None,
    install_cmds: list | None = None,
    verify_cmd: str = "true",
) -> dict:
    return {
        "surface": "browser",
        "tool": "playwright",
        "tool_version": "1.51.0",
        "files_to_create": files_to_create or [],
        "files_to_modify": files_to_modify or [],
        "install_cmds": install_cmds or ["true"],
        "verify_cmd": verify_cmd,
        "branch_name": "scaffold/test",
        "commit_msg": "test",
    }


class _ApplyTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="scaffold-test-repo-"))
        self._snapshots_to_clean: list[Path] = []

    def tearDown(self) -> None:
        shutil.rmtree(self.repo, ignore_errors=True)
        for snap in self._snapshots_to_clean:
            shutil.rmtree(snap, ignore_errors=True)

    def _track_snapshot(self, result: ApplyResult) -> None:
        if result.snapshot_dir:
            self._snapshots_to_clean.append(Path(result.snapshot_dir))


class TestApplyPlanHappyPath(_ApplyTestBase):
    def test_returns_apply_result_dataclass(self) -> None:
        result = apply_plan(_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertIsInstance(result, ApplyResult)

    def test_writes_files_to_create(self) -> None:
        plan = _plan(
            files_to_create=[
                {
                    "path": "tests/acceptance/example.spec.ts",
                    "description": "happy-path test",
                    "body": "export default 'hi';\n",
                }
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        target = self.repo / "tests/acceptance/example.spec.ts"
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "export default 'hi';\n")

    def test_creates_intermediate_directories(self) -> None:
        plan = _plan(
            files_to_create=[
                {"path": "a/b/c/deep.ts", "description": "deep", "body": "x\n"}
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertTrue((self.repo / "a/b/c/deep.ts").exists())

    def test_overwrites_files_to_modify(self) -> None:
        manifest = self.repo / "package.json"
        manifest.write_text('{"name": "demo"}\n')
        plan = _plan(
            files_to_modify=[
                {
                    "path": "package.json",
                    "description": "+dep",
                    "body": '{"name": "demo", "x": "y"}\n',
                }
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertIn('"x": "y"', manifest.read_text())

    def test_runs_install_commands(self) -> None:
        sentinel = self.repo / "install-ran"
        plan = _plan(install_cmds=[f"touch {sentinel}"])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(sentinel.exists())

    def test_runs_verify_command(self) -> None:
        sentinel = self.repo / "verify-ran"
        plan = _plan(verify_cmd=f"touch {sentinel}")
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(sentinel.exists())

    def test_install_runs_before_verify(self) -> None:
        sentinel = self.repo / "install-marker"
        plan = _plan(
            install_cmds=[f"touch {sentinel}"],
            verify_cmd=f"test -e {sentinel}",
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok, result.reason)

    def test_snapshot_id_populated_on_success(self) -> None:
        result = apply_plan(_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.snapshot_id)
        self.assertTrue(result.snapshot_id)
        self.assertIsNotNone(result.snapshot_dir)
        self.assertTrue(Path(result.snapshot_dir).exists())

    def test_no_failure_fields_on_success(self) -> None:
        result = apply_plan(_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertIsNone(result.phase)
        self.assertIsNone(result.reason)
        self.assertFalse(result.reverted)


if __name__ == "__main__":
    unittest.main()
