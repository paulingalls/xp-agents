#!/usr/bin/env python3
"""Tests for scaffold_apply.py — pre-flight validation + lifecycle.

Covers rejection of pre-existing create targets, rejection of modify
on missing files, phase-log emission, snapshot cleanup, and ApplyResult
lifecycle. Reuses `_plan`, `_ApplyTestBase`, `_RevertTestBase` from the
sibling pipeline file (test_scaffold_apply_pipeline.py).
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import scaffold_apply
from _helpers import make_fake_copy_failing_on_backup_restore
from scaffold_apply import ApplyResult, apply_plan
from test_scaffold_apply_pipeline import _ApplyTestBase, _plan, _RevertTestBase


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
        assert result.snapshot_dir is not None
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
        assert result.snapshot_dir is not None
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
        assert result.snapshot_dir is not None
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
        fake_copy = make_fake_copy_failing_on_backup_restore(shutil.copy2)
        with mock.patch.object(shutil, "copy2", side_effect=fake_copy):
            result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertNotEqual(result.unrestored, [])
        assert result.snapshot_dir is not None
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


class TestRunVerifyIdentity(_ApplyTestBase):
    """Bug 1: a successful install can still land the wrong binary
    (`brew install --cask maestro` → Maestro.app GUI). The apply
    pipeline runs verify_identity_cmd between install and verify; if
    its stdout fails expected_version_pattern, the snapshot reverts
    just like an install failure."""

    def _identity_plan(self, *, cmd: str, pattern: str) -> dict:
        plan = _plan(install_cmds=["true"], verify_cmd="true")
        plan["verify_identity_cmd"] = cmd
        plan["expected_version_pattern"] = pattern
        return plan

    def test_pattern_matches_returns_ok(self) -> None:
        # `printf` is POSIX-portable and produces deterministic stdout.
        plan = self._identity_plan(
            cmd="printf 'Maestro 2.5.1\\n'",
            pattern=r"^Maestro \d+\.",
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok, result.reason)

    def test_pattern_mismatch_reverts(self) -> None:
        plan = self._identity_plan(
            cmd="printf 'Maestro.app v0.15.4\\n'",
            pattern=r"^Maestro \d+\.",
        )
        # Add a real created file to verify revert removes it.
        plan["files_to_create"] = [
            {"path": "tests/sentinel.spec.ts", "description": "sentinel", "body": "x\n"}
        ]
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertEqual(result.phase, "verify-identity")
        self.assertTrue(result.reverted)
        # Created file gone (revert ran).
        self.assertFalse((self.repo / "tests" / "sentinel.spec.ts").exists())

    def test_pattern_mismatch_reason_names_pattern(self) -> None:
        plan = self._identity_plan(
            cmd="printf 'Wrong Tool\\n'",
            pattern=r"^Maestro \d+\.",
        )
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertFalse(result.ok)
        self.assertIn("Maestro", result.reason or "")

    def test_empty_cmd_skips_phase(self) -> None:
        # No verify_identity_cmd → back-compat: pipeline runs install + verify only.
        plan = _plan(install_cmds=["true"], verify_cmd="true")
        # Explicitly leave verify_identity_cmd unset (default empty).
        result = apply_plan(plan, repo_root=self.repo)
        self._track_snapshot(result)
        self.assertTrue(result.ok, result.reason)

    def test_cmd_set_but_pattern_empty_raises(self) -> None:
        # Honest refusal: hand-rolled plan with cmd but no pattern would
        # silently accept any --version output. ValueError surfaces the bug
        # to the caller instead of letting the guard silently degrade.
        from scaffold_apply import ApplySnapshot, create_snapshot, run_verify_identity

        plan = _plan()
        plan["verify_identity_cmd"] = "true"
        plan["expected_version_pattern"] = ""
        snap: ApplySnapshot = create_snapshot(plan, repo_root=self.repo)
        self._snapshots_to_clean.append(snap.snapshot_dir)
        with self.assertRaises(ValueError) as cm:
            run_verify_identity(snap)
        self.assertIn("expected_version_pattern", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
