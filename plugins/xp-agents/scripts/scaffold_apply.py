#!/usr/bin/env python3
"""Write/install/verify/atomic-revert pipeline for /xp-scaffold-acceptance.

Public API:

- ``apply_plan(plan, *, repo_root)`` — full pipeline. Snapshots every
  ``files_to_modify`` target, writes ``files_to_create`` and
  ``files_to_modify`` bodies, runs ``install_cmds`` then ``verify_cmd``.
  Returns ``ApplyResult(ok=True)`` on green. Any phase failure (write
  OSError, install/verify non-zero exit, or timeout) auto-reverts the
  snapshot and returns ``ApplyResult(ok=False, phase=..., reason=...,
  reverted=True)`` with the failing phase's stderr in ``reason``. If
  revert itself can't fully restore (e.g., target file became
  unwritable), ``unrestored`` lists the relpaths and ``recovery`` carries
  a manual-recovery message naming the snapshot directory.

- Phase helpers ``create_snapshot``, ``write_files``, ``run_install``,
  ``run_verify``, ``revert`` are exposed for the cycle-5 CLI surface
  (apply-write / apply-install / apply-verify / apply-revert subcommands).

Snapshot layout (under ``${TMPDIR}/scaffold-snap-<id>``):

    backup/<relpath>   — copy of every files_to_modify target before write
    plan.json          — full plan persisted at snapshot time. Revert reads
                         plan.files_to_create from in-memory snap; the
                         on-disk plan.json is for the cycle-5 CLI to
                         re-load state across phase boundaries. Unlink is
                         missing_ok so partial-write states revert cleanly.

Subprocess discipline: install/verify run with ``shell=False``; commands
are split via ``shlex.split`` so the canonical / web-refreshed knowledge
the skill provides is interpreted as argv, not a shell string. stdout is
discarded (npm install / pip install -v emit MBs of progress); stderr is
captured for failure diagnostics. Timeouts: 300s install, 60s verify.
"""

import contextlib
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import write_text_atomic

INSTALL_TIMEOUT_SEC = 300
VERIFY_TIMEOUT_SEC = 60
SNAPSHOT_PREFIX = "scaffold-snap-"
BACKUP_SUBDIR = "backup"
PLAN_FILE = "plan.json"


@dataclass
class ApplyResult:
    ok: bool
    snapshot_id: str | None = None
    snapshot_dir: str | None = None
    phase: str | None = None
    reason: str | None = None
    reverted: bool = False
    unrestored: list[str] = field(default_factory=list)
    recovery: str | None = None


@dataclass
class ApplySnapshot:
    snapshot_id: str
    snapshot_dir: Path
    repo_root: Path
    plan: dict


def _new_snapshot_dir() -> tuple[str, Path]:
    snapshot_id = uuid.uuid4().hex[:12]
    snapshot_dir = Path(tempfile.gettempdir()) / f"{SNAPSHOT_PREFIX}{snapshot_id}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    (snapshot_dir / BACKUP_SUBDIR).mkdir()
    return snapshot_id, snapshot_dir


def create_snapshot(plan: dict, *, repo_root: Path) -> ApplySnapshot:
    """Create snapshot dir + plan.json, back up every files_to_modify target.

    No repo writes happen here — bodies land in ``write_files``. Splitting
    snapshot creation from body writes lets ``apply_plan`` revert partial
    writes when ``write_files`` itself raises.
    """
    snapshot_id, snapshot_dir = _new_snapshot_dir()
    backup_dir = snapshot_dir / BACKUP_SUBDIR
    for entry in plan.get("files_to_modify", []):
        target = repo_root / entry["path"]
        backup = backup_dir / entry["path"]
        backup.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            shutil.copy2(target, backup)
    snap = ApplySnapshot(
        snapshot_id=snapshot_id,
        snapshot_dir=snapshot_dir,
        repo_root=repo_root,
        plan=plan,
    )
    write_text_atomic(snap.snapshot_dir / PLAN_FILE, json.dumps(plan))
    return snap


def write_files(snap: ApplySnapshot) -> None:
    """Atomically write every files_to_modify body and every files_to_create body."""
    plan = snap.plan
    for entry in plan.get("files_to_modify", []):
        if "body" not in entry:
            continue
        target = snap.repo_root / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(target, entry["body"])
    for entry in plan.get("files_to_create", []):
        target = snap.repo_root / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(target, entry.get("body", ""))


def run_install(snap: ApplySnapshot) -> None:
    """Run each install_cmds entry in repo_root. Raises CalledProcessError."""
    for cmd in snap.plan.get("install_cmds", []):
        subprocess.run(
            shlex.split(cmd),
            cwd=snap.repo_root,
            check=True,
            timeout=INSTALL_TIMEOUT_SEC,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )


def run_verify(snap: ApplySnapshot) -> None:
    """Run verify_cmd in repo_root. Raises CalledProcessError on non-zero."""
    cmd = snap.plan.get("verify_cmd")
    if not cmd:
        return
    subprocess.run(
        shlex.split(cmd),
        cwd=snap.repo_root,
        check=True,
        timeout=VERIFY_TIMEOUT_SEC,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def revert(snap: ApplySnapshot) -> list[str]:
    """Restore snapshot. Returns relpaths that could not be restored."""
    unrestored: list[str] = []
    backup_dir = snap.snapshot_dir / BACKUP_SUBDIR
    for entry in snap.plan.get("files_to_modify", []):
        rel = entry["path"]
        try:
            shutil.copy2(backup_dir / rel, snap.repo_root / rel)
        except FileNotFoundError:
            pass
        except OSError:
            unrestored.append(rel)
    for entry in snap.plan.get("files_to_create", []):
        rel = entry["path"]
        try:
            (snap.repo_root / rel).unlink(missing_ok=True)
        except OSError:
            unrestored.append(rel)
    return unrestored


def _phase_failure_reason(exc: BaseException, *, timeout_sec: int) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"timeout after {timeout_sec}s"
    stderr = getattr(exc, "stderr", "") or ""
    return stderr.strip() or str(exc)


def _failure(phase: str, reason: str, snap: ApplySnapshot) -> ApplyResult:
    unrestored = revert(snap)
    recovery = None
    if unrestored:
        recovery = (
            f"Manual recovery required: {len(unrestored)} file(s) could not be "
            f"restored. Snapshot retained at {snap.snapshot_dir}. "
            f"Unrestored: {', '.join(unrestored)}"
        )
    return ApplyResult(
        ok=False,
        phase=phase,
        reason=reason,
        reverted=True,
        unrestored=unrestored,
        snapshot_id=snap.snapshot_id,
        snapshot_dir=str(snap.snapshot_dir),
        recovery=recovery,
    )


def apply_plan(plan: dict, *, repo_root: Path) -> ApplyResult:
    """Drive write → install → verify; auto-revert the snapshot on any failure."""
    snap = create_snapshot(plan, repo_root=repo_root)
    try:
        write_files(snap)
    except OSError as exc:
        return _failure("write", str(exc), snap)
    try:
        run_install(snap)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return _failure(
            "install",
            _phase_failure_reason(exc, timeout_sec=INSTALL_TIMEOUT_SEC),
            snap,
        )
    try:
        run_verify(snap)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return _failure(
            "verify",
            _phase_failure_reason(exc, timeout_sec=VERIFY_TIMEOUT_SEC),
            snap,
        )
    return ApplyResult(
        ok=True,
        snapshot_id=snap.snapshot_id,
        snapshot_dir=str(snap.snapshot_dir),
    )
