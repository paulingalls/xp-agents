#!/usr/bin/env python3
"""Apply-lifecycle subcommands for scaffold_cli.

Houses the seven ``_cmd_apply_*`` callables (write/install/verify-identity/
verify/revert/commit/record) plus the helpers used by them
(``_load_snapshot_or_exit``, ``_run_apply_phase``) and the shared CLI
utilities (``_emit`` JSON-stdout, ``_require_smm_dir`` precondition,
``_load_stdin_json`` input-or-die). ``scaffold_cli`` re-exports every
name so ``from scaffold_cli import _cmd_apply_write`` still resolves.

Extracted from scaffold_cli.py to keep both modules under the
500-line project budget.
"""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branching
import scaffold_apply
import scaffold_post


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0


def _require_smm_dir(args: argparse.Namespace, command: str) -> int | None:
    if args.smm_dir is None:
        print(f"--smm-dir is required for {command}", file=sys.stderr)
        return 2
    return None


def _load_stdin_json() -> Any:
    try:
        return json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON on stdin: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _cmd_apply_write(args: argparse.Namespace) -> int:
    plan = _load_stdin_json()
    result, _snap = scaffold_apply.apply_write_only(plan, repo_root=args.repo_root)
    return _emit(asdict(result))


def _load_snapshot_or_exit(
    snapshot_id: str, repo_root: Path
) -> scaffold_apply.ApplySnapshot:
    try:
        return scaffold_apply.load_snapshot(snapshot_id, repo_root=repo_root)
    except FileNotFoundError as exc:
        print(f"Snapshot not found: {snapshot_id} ({exc})", file=sys.stderr)
        raise SystemExit(2) from exc


def _run_apply_phase(
    args: argparse.Namespace,
    *,
    phase: str,
    run_fn,
    timeout_sec: int,
    cleanup_on_success: bool,
) -> int:
    snap = _load_snapshot_or_exit(args.snapshot_id, args.repo_root)
    try:
        run_fn(snap)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        reason = scaffold_apply.phase_failure_reason(
            exc, timeout_sec=timeout_sec, log_path=snap.log_path(phase)
        )
        return _emit(asdict(scaffold_apply.failure_result(phase, reason, snap)))
    if cleanup_on_success:
        scaffold_apply.cleanup_snapshot(snap)
        result = scaffold_apply.ApplyResult(
            ok=True, snapshot_id=snap.snapshot_id, snapshot_state="cleaned"
        )
    else:
        result = scaffold_apply.ApplyResult(
            ok=True,
            snapshot_id=snap.snapshot_id,
            snapshot_dir=str(snap.snapshot_dir),
            snapshot_state="retained",
        )
    return _emit(asdict(result))


def _cmd_apply_install(args: argparse.Namespace) -> int:
    return _run_apply_phase(
        args,
        phase="install",
        run_fn=scaffold_apply.run_install,
        timeout_sec=scaffold_apply.INSTALL_TIMEOUT_SEC,
        cleanup_on_success=False,
    )


def _cmd_apply_verify_identity(args: argparse.Namespace) -> int:
    return _run_apply_phase(
        args,
        phase="verify-identity",
        run_fn=scaffold_apply.run_verify_identity,
        timeout_sec=scaffold_apply.IDENTITY_VERIFY_TIMEOUT_SEC,
        cleanup_on_success=False,
    )


def _cmd_apply_verify(args: argparse.Namespace) -> int:
    return _run_apply_phase(
        args,
        phase="verify",
        run_fn=scaffold_apply.run_verify,
        timeout_sec=scaffold_apply.VERIFY_TIMEOUT_SEC,
        cleanup_on_success=False,  # apply-record is the terminal phase
    )


def _cmd_apply_commit(args: argparse.Namespace) -> int:
    err = _require_smm_dir(args, "apply-commit")
    if err is not None:
        return err
    snap = _load_snapshot_or_exit(args.snapshot_id, args.repo_root)
    stage = branching.get_branching_stage(args.smm_dir)
    tool_version = snap.plan["tool_version"]
    result = scaffold_post.commit_scaffold(
        snap,
        smm_dir=args.smm_dir,
        stage=stage,
        surface=args.surface,
        tool=args.tool,
        tool_version=tool_version,
        concern_id=args.concern_id,
    )
    return _emit(asdict(result))


def _cmd_apply_record(args: argparse.Namespace) -> int:
    err = _require_smm_dir(args, "apply-record")
    if err is not None:
        return err
    snap = _load_snapshot_or_exit(args.snapshot_id, args.repo_root)
    verify_cmd = snap.plan["verify_cmd"]
    result = scaffold_post.record_scaffold(
        snap,
        smm_dir=args.smm_dir,
        surface=args.surface,
        verify_cmd=verify_cmd,
        concern_id=args.concern_id,
        agent_id=args.agent_id,
        commit_sha=args.commit_sha,
    )
    if result.ok:
        scaffold_apply.cleanup_snapshot(snap)  # apply-record is the terminal phase
    return _emit(asdict(result))


def _cmd_apply_revert(args: argparse.Namespace) -> int:
    snap = _load_snapshot_or_exit(args.snapshot_id, args.repo_root)
    unrestored = scaffold_apply.revert(snap)
    snapshot_dir: str | None = str(snap.snapshot_dir)
    if not unrestored:
        scaffold_apply.cleanup_snapshot(snap)
        snapshot_dir = None
    return _emit(
        {
            "ok": not unrestored,
            "unrestored": unrestored,
            "snapshot_dir": snapshot_dir,
        }
    )
