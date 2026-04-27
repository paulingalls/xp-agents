#!/usr/bin/env python3
"""Tests for scaffold_apply.py — write/install/verify/atomic-revert pipeline."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import scaffold_apply
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
        # snapshot_dir is None on success — directory is auto-cleaned up.
        self.assertIsNone(result.snapshot_dir)

    def test_no_failure_fields_on_success(self) -> None:
        result = apply_plan(_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertIsNone(result.phase)
        self.assertIsNone(result.reason)
        self.assertFalse(result.reverted)


class _RevertTestBase(_ApplyTestBase):
    """Sets up a manifest with pre-existing content + a creating-and-modifying plan."""

    def setUp(self) -> None:
        super().setUp()
        self.manifest = self.repo / "package.json"
        self.manifest.write_text('{"name": "demo"}\n', encoding="utf-8")
        self.created_target = self.repo / "tests/x.spec.ts"

    def _build_plan(self, **overrides: object) -> dict:
        plan = _plan(
            files_to_create=[
                {"path": "tests/x.spec.ts", "description": "spec", "body": "x\n"}
            ],
            files_to_modify=[
                {
                    "path": "package.json",
                    "description": "+dep",
                    "body": '{"name": "demo", "added": true}\n',
                }
            ],
        )
        plan.update(overrides)
        return plan

    def _assert_pre_state_restored(self) -> None:
        self.assertFalse(self.created_target.exists())
        self.assertEqual(
            self.manifest.read_text(encoding="utf-8"),
            '{"name": "demo"}\n',
        )


class TestApplyPlanRevertOnInstallFailure(_RevertTestBase):
    def test_install_failure_returns_not_ok(self) -> None:
        plan = self._build_plan(install_cmds=["false"])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)

    def test_install_failure_phase_recorded(self) -> None:
        plan = self._build_plan(install_cmds=["false"])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertEqual(result.phase, "install")

    def test_install_failure_reverted_flag(self) -> None:
        plan = self._build_plan(install_cmds=["false"])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.reverted)
        self.assertEqual(result.unrestored, [])
        self.assertIsNone(result.recovery)

    def test_install_failure_pre_state_restored(self) -> None:
        plan = self._build_plan(install_cmds=["false"])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self._assert_pre_state_restored()

    def test_install_failure_stderr_in_reason(self) -> None:
        plan = self._build_plan(
            install_cmds=['sh -c "echo BANG_FROM_INSTALL >&2; exit 1"']
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertIn("BANG_FROM_INSTALL", result.reason or "")


class TestApplyPlanRevertOnVerifyFailure(_RevertTestBase):
    def test_verify_failure_returns_not_ok(self) -> None:
        plan = self._build_plan(verify_cmd="false")
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)

    def test_verify_failure_phase_recorded(self) -> None:
        plan = self._build_plan(verify_cmd="false")
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertEqual(result.phase, "verify")

    def test_verify_failure_pre_state_restored(self) -> None:
        plan = self._build_plan(verify_cmd="false")
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self._assert_pre_state_restored()
        self.assertTrue(result.reverted)

    def test_verify_failure_stderr_in_reason(self) -> None:
        plan = self._build_plan(verify_cmd='sh -c "echo BANG_FROM_VERIFY >&2; exit 1"')
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertIn("BANG_FROM_VERIFY", result.reason or "")


class TestApplyPlanRevertOnWriteFailure(_RevertTestBase):
    def test_write_failure_returns_not_ok(self) -> None:
        plan = self._build_plan()

        original_write = scaffold_apply.write_text_atomic
        call_count = {"n": 0}

        def fake_write(path: Path, content: str, **kw: object) -> None:
            call_count["n"] += 1
            if "x.spec.ts" in str(path):
                raise OSError("simulated write failure")
            original_write(path, content, **kw)

        with mock.patch.object(scaffold_apply, "write_text_atomic", fake_write):
            result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)

        self.assertFalse(result.ok)
        self.assertEqual(result.phase, "write")
        self.assertTrue(result.reverted)

    def test_write_failure_pre_state_restored(self) -> None:
        plan = self._build_plan()

        original_write = scaffold_apply.write_text_atomic

        def fake_write(path: Path, content: str, **kw: object) -> None:
            if "x.spec.ts" in str(path):
                raise OSError("simulated write failure")
            original_write(path, content, **kw)

        with mock.patch.object(scaffold_apply, "write_text_atomic", fake_write):
            result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)

        self._assert_pre_state_restored()


class TestApplyPlanRevertOfRevertFailure(_RevertTestBase):
    """Failure path: a phase fails AND the subsequent revert can't fully restore."""

    def _force_revert_break(self) -> None:
        """Patch shutil.copy2 to raise PermissionError when restoring backup→target."""
        original_copy = shutil.copy2

        def fake_copy(src, dst, *args, **kw):  # type: ignore[no-untyped-def]
            if "scaffold-snap-" in str(src) and "/backup/" in str(src):
                raise PermissionError("simulated restore failure")
            return original_copy(src, dst, *args, **kw)

        patcher = mock.patch.object(shutil, "copy2", side_effect=fake_copy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run_with_broken_revert(self) -> ApplyResult:
        plan = self._build_plan(install_cmds=["false"])
        self._force_revert_break()
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        return result

    def test_install_then_revert_failure_records_unrestored(self) -> None:
        result = self._run_with_broken_revert()
        self.assertFalse(result.ok)
        self.assertEqual(result.phase, "install")
        self.assertIn("package.json", result.unrestored)

    def test_recovery_message_names_snapshot_dir(self) -> None:
        result = self._run_with_broken_revert()
        self.assertIsNotNone(result.recovery)
        self.assertIn(result.snapshot_dir, result.recovery)

    def test_recovery_message_lists_unrestored_paths(self) -> None:
        result = self._run_with_broken_revert()
        self.assertIn("package.json", result.recovery)

    def test_recovery_message_mentions_manual(self) -> None:
        result = self._run_with_broken_revert()
        self.assertRegex(result.recovery or "", r"(?i)manual")


class TestApplyPlanRejectsPreExistingCreateTargets(_ApplyTestBase):
    """Block fix: a misclassified files_to_create entry pointing at an
    existing customer file would be silently overwritten by write_files
    and then deleted by revert(). apply_plan must refuse before any
    snapshot is created."""

    def _run_collision(
        self, target_rel: str = "package.json", content: str = '{"name": "demo"}\n'
    ) -> tuple[Path, ApplyResult]:
        target = self.repo / target_rel
        target.write_text(content, encoding="utf-8")
        plan = _plan(
            files_to_create=[
                {"path": target_rel, "description": "should fail", "body": "x\n"}
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        return target, result

    def test_pre_existing_create_target_returns_not_ok(self) -> None:
        _, result = self._run_collision()
        self.assertFalse(result.ok)
        self.assertEqual(result.phase, "write")

    def test_pre_existing_create_target_reason_names_path(self) -> None:
        _, result = self._run_collision()
        self.assertIn("package.json", result.reason or "")

    def test_pre_existing_create_target_does_not_touch_file(self) -> None:
        original = '{"name": "demo", "secret": "preserved"}\n'
        target, _ = self._run_collision(content=original)
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_pre_existing_create_target_no_snapshot_created(self) -> None:
        _, result = self._run_collision()
        self.assertFalse(result.reverted)
        self.assertIsNone(result.snapshot_id)
        self.assertIsNone(result.snapshot_dir)

    def test_clean_plan_passes_validation(self) -> None:
        plan = _plan(
            files_to_create=[
                {"path": "tests/new.spec.ts", "description": "new", "body": "x\n"}
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)


class TestApplyPlanRejectsModifyOfNonexistent(_ApplyTestBase):
    """Symmetric to the create-side guard: a misclassified files_to_modify
    entry pointing at a path that doesn't yet exist would silently create
    the file via write_files and then orphan it (revert can't restore a
    backup that doesn't exist). apply_plan must refuse before any
    snapshot is created."""

    def _modify_only_plan(self, target_rel: str = "package.json") -> dict:
        return _plan(
            files_to_modify=[
                {
                    "path": target_rel,
                    "description": "should fail",
                    "body": '{"x": 1}\n',
                }
            ]
        )

    def test_modify_of_nonexistent_returns_not_ok(self) -> None:
        result = apply_plan(self._modify_only_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertEqual(result.phase, "write")

    def test_modify_of_nonexistent_reason_names_path(self) -> None:
        result = apply_plan(self._modify_only_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertIn("package.json", result.reason or "")

    def test_modify_of_nonexistent_no_snapshot_created(self) -> None:
        result = apply_plan(self._modify_only_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.reverted)
        self.assertIsNone(result.snapshot_id)
        self.assertIsNone(result.snapshot_dir)

    def test_modify_of_nonexistent_target_not_created(self) -> None:
        target = self.repo / "package.json"
        result = apply_plan(self._modify_only_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(target.exists())

    def test_pre_existing_modify_target_passes_validation(self) -> None:
        target = self.repo / "package.json"
        target.write_text('{"name": "demo"}\n', encoding="utf-8")
        result = apply_plan(self._modify_only_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)

    def test_create_collision_wins_when_both_violations_present(self) -> None:
        """When the plan has both a missing-modify and an existing-create
        violation, the create-collision reason wins. Locks in deterministic
        error messaging so callers see a stable contract."""
        existing = self.repo / "package.json"
        existing.write_text('{"name": "demo"}\n', encoding="utf-8")
        plan = _plan(
            files_to_create=[
                {"path": "package.json", "description": "collision", "body": "x"}
            ],
            files_to_modify=[
                {
                    "path": "tests/missing.ts",
                    "description": "missing",
                    "body": "x",
                }
            ],
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertIn("package.json", result.reason or "")
        self.assertIn("files_to_create", result.reason or "")


class TestApplyPhaseLogs(_ApplyTestBase):
    """Each phase (install, verify) writes its stdout to a log file under
    snapshot_dir, named `{phase}.log`. On failure the reason field includes
    the log path so the customer can inspect the firehose. stderr stays
    captured into reason directly for the brief summary."""

    def test_run_install_writes_install_log(self) -> None:
        # Test the phase helper directly — apply_plan cleans up on success.
        plan = _plan(install_cmds=["echo install-output"])
        snap = scaffold_apply.create_snapshot(plan, repo_root=self.repo)
        self._snapshots_to_clean.append(snap.snapshot_dir)
        scaffold_apply.run_install(snap)
        log = snap.log_path("install")
        self.assertTrue(log.exists())
        self.assertIn("install-output", log.read_text(encoding="utf-8"))

    def test_run_verify_writes_verify_log(self) -> None:
        plan = _plan(verify_cmd="echo verify-output")
        snap = scaffold_apply.create_snapshot(plan, repo_root=self.repo)
        self._snapshots_to_clean.append(snap.snapshot_dir)
        scaffold_apply.run_verify(snap)
        log = snap.log_path("verify")
        self.assertTrue(log.exists())
        self.assertIn("verify-output", log.read_text(encoding="utf-8"))

    def test_install_failure_reason_includes_log_path(self) -> None:
        plan = _plan(
            install_cmds=['sh -c "echo to-stdout; echo to-stderr >&2; exit 1"']
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertIn("install.log", result.reason or "")

    def test_install_failure_reason_includes_stderr_summary(self) -> None:
        plan = _plan(install_cmds=['sh -c "echo BANG-INSTALL-STDERR >&2; exit 1"'])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertIn("BANG-INSTALL-STDERR", result.reason or "")

    def test_install_log_captures_stdout_on_failure(self) -> None:
        plan = _plan(install_cmds=['sh -c "echo from-stdout; exit 1"'])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        log = Path(result.snapshot_dir) / "install.log"
        self.assertTrue(log.exists())
        self.assertIn("from-stdout", log.read_text(encoding="utf-8"))

    def test_verify_failure_reason_includes_verify_log_path(self) -> None:
        plan = _plan(verify_cmd='sh -c "exit 1"')
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertIn("verify.log", result.reason or "")

    def test_install_log_and_verify_log_coexist_after_verify_failure(self) -> None:
        plan = _plan(
            install_cmds=["echo install-trace"],
            verify_cmd='sh -c "echo verify-trace; exit 1"',
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        snap_dir = Path(result.snapshot_dir)
        self.assertTrue((snap_dir / "install.log").exists())
        self.assertTrue((snap_dir / "verify.log").exists())
        self.assertIn(
            "install-trace",
            (snap_dir / "install.log").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "verify-trace",
            (snap_dir / "verify.log").read_text(encoding="utf-8"),
        )


class TestApplyPlanCleansUpSnapshot(_ApplyTestBase):
    """apply_plan must clean up snapshot_dir on success paths.

    On ok=True: cleanup; result.snapshot_dir is None.
    On failure with clean revert (unrestored=[]): cleanup; snapshot_dir is None.
    On failure with unrestored != []: retain; snapshot_dir populated for the
    customer's manual recovery (and recovery message names it)."""

    def test_apply_plan_success_removes_snapshot_dir(self) -> None:
        result = apply_plan(_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertIsNone(result.snapshot_dir)

    def test_apply_plan_success_disk_dir_gone(self) -> None:
        # Capture by creating snapshot ourselves so we can check after cleanup.
        result = apply_plan(_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        # The snapshot_id is preserved on the result so callers can correlate;
        # the dir under TMPDIR derived from that id must be gone.
        snapshot_dir = (
            Path(tempfile.gettempdir()) / f"scaffold-snap-{result.snapshot_id}"
        )
        self.assertFalse(snapshot_dir.exists())

    def test_apply_plan_clean_revert_retains_snapshot_for_log_inspection(
        self,
    ) -> None:
        """Clean-revert failure retains the snapshot so the per-phase log
        file referenced in `reason` (e.g. 'see install.log') survives for
        customer inspection. Cleanup happens only on success paths."""
        manifest = self.repo / "package.json"
        manifest.write_text('{"name": "demo"}\n', encoding="utf-8")
        plan = _plan(
            files_to_create=[
                {"path": "tests/x.spec.ts", "description": "spec", "body": "x\n"}
            ],
            files_to_modify=[
                {
                    "path": "package.json",
                    "description": "+dep",
                    "body": '{"name": "demo", "added": true}\n',
                }
            ],
            install_cmds=["false"],
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertEqual(result.unrestored, [])
        self.assertIsNotNone(result.snapshot_dir)
        self.assertTrue(Path(result.snapshot_dir).exists())
        self.assertTrue((Path(result.snapshot_dir) / "install.log").exists())

    def test_apply_plan_retains_snapshot_when_unrestored(self) -> None:
        manifest = self.repo / "package.json"
        manifest.write_text('{"name": "demo"}\n', encoding="utf-8")
        plan = _plan(
            files_to_modify=[
                {
                    "path": "package.json",
                    "description": "+dep",
                    "body": '{"name": "demo", "added": true}\n',
                }
            ],
            install_cmds=["false"],
        )
        original_copy = shutil.copy2

        def fake_copy(src, dst, *args, **kw):  # type: ignore[no-untyped-def]
            if "scaffold-snap-" in str(src) and "/backup/" in str(src):
                raise PermissionError("simulated restore failure")
            return original_copy(src, dst, *args, **kw)

        with mock.patch.object(shutil, "copy2", side_effect=fake_copy):
            result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertNotEqual(result.unrestored, [])
        self.assertIsNotNone(result.snapshot_dir)
        self.assertTrue(Path(result.snapshot_dir).exists())
        self.assertIn(result.snapshot_dir, result.recovery or "")


class TestApplyResultLifecycle(_ApplyTestBase):
    """ApplyResult.snapshot_state distinguishes never-had / cleaned-up / on-disk.

    Closes debt 5cb9c753dc13: the snapshot_dir field overloads location +
    lifecycle (None means both 'cleaned up' and 'never had a snapshot').
    A dedicated state field makes the lifecycle unambiguous.
    """

    def test_success_path_state_is_cleaned(self) -> None:
        result = apply_plan(_plan(), repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok)
        self.assertEqual(result.snapshot_state, "cleaned")
        self.assertIsNone(result.snapshot_dir)

    def test_validation_failure_state_is_none(self) -> None:
        target = self.repo / "package.json"
        target.write_text('{"name": "demo"}\n', encoding="utf-8")
        plan = _plan(
            files_to_create=[
                {"path": "package.json", "description": "collides", "body": "x\n"}
            ]
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertEqual(result.snapshot_state, "none")
        self.assertIsNone(result.snapshot_dir)


class TestApplyResultLifecycleRetained(_RevertTestBase):
    def test_install_failure_state_is_retained(self) -> None:
        plan = self._build_plan(install_cmds=["false"])
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertEqual(result.snapshot_state, "retained")
        self.assertIsNotNone(result.snapshot_dir)


if __name__ == "__main__":
    unittest.main()
