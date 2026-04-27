#!/usr/bin/env python3
"""Write/install/verify/atomic-revert pipeline for /xp-scaffold-acceptance.

Public API (cycle 2 — happy path only; revert/error paths land cycles 3-4):

- ``apply_plan(plan, *, repo_root)`` — happy-path driver. Snapshots every
  ``files_to_modify`` target, writes ``files_to_create`` and
  ``files_to_modify`` bodies, runs ``install_cmds`` then ``verify_cmd``.
  Returns ``ApplyResult(ok=True)`` on green; subprocess.CalledProcessError
  / OSError propagate uncaught for now (cycle 3 wraps them in auto-revert).

- Phase helpers ``snapshot_and_write``, ``run_install``, ``run_verify``,
  ``revert`` are exposed for the CLI surface — each apply-* subcommand
  (cycle 5) maps to one helper.

Snapshot layout (under ``${TMPDIR}/scaffold-snap-<id>``):

    backup/<relpath>   — copy of every files_to_modify target before write
    plan.json          — full plan persisted by apply-write so apply-install,
                         apply-verify, apply-revert can re-load it
    created.txt        — newline-separated relpaths of files apply-write
                         actually created (revert unlinks these)

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
CREATED_FILE = "created.txt"


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
    created_paths: list[Path] = field(default_factory=list)


def _new_snapshot_dir() -> tuple[str, Path]:
    snapshot_id = uuid.uuid4().hex[:12]
    snapshot_dir = Path(tempfile.gettempdir()) / f"{SNAPSHOT_PREFIX}{snapshot_id}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    (snapshot_dir / BACKUP_SUBDIR).mkdir()
    return snapshot_id, snapshot_dir


def _persist_state(snap: ApplySnapshot) -> None:
    write_text_atomic(snap.snapshot_dir / PLAN_FILE, json.dumps(snap.plan))
    rels = [str(p.relative_to(snap.repo_root)) for p in snap.created_paths]
    write_text_atomic(snap.snapshot_dir / CREATED_FILE, "\n".join(rels))


def snapshot_and_write(plan: dict, *, repo_root: Path) -> ApplySnapshot:
    """Snapshot every files_to_modify target, then write all bodies.

    For each modify-entry: best-effort copy the existing file into
    ``backup/<relpath>`` (silently skipped when the target doesn't yet
    exist), then atomically write the new body. For each create-entry:
    atomically write the body and record the path so revert can unlink.
    Plan + created list are persisted to ``snapshot_dir`` so cycle-5 CLI
    subcommands can re-load them across phase boundaries.
    """
    snapshot_id, snapshot_dir = _new_snapshot_dir()
    backup_dir = snapshot_dir / BACKUP_SUBDIR
    snap = ApplySnapshot(
        snapshot_id=snapshot_id,
        snapshot_dir=snapshot_dir,
        repo_root=repo_root,
        plan=plan,
    )
    for entry in plan.get("files_to_modify", []):
        target = repo_root / entry["path"]
        backup = backup_dir / entry["path"]
        backup.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(FileNotFoundError):
            shutil.copy2(target, backup)
        if "body" in entry:
            target.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(target, entry["body"])
    for entry in plan.get("files_to_create", []):
        target = repo_root / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(target, entry.get("body", ""))
        snap.created_paths.append(target)
    _persist_state(snap)
    return snap


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
    for created in snap.created_paths:
        try:
            created.unlink(missing_ok=True)
        except OSError:
            unrestored.append(str(created.relative_to(snap.repo_root)))
    return unrestored


def apply_plan(plan: dict, *, repo_root: Path) -> ApplyResult:
    """Drive the write → install → verify pipeline (happy path only).

    Cycle 3 will wrap phases in try/except + auto-revert; cycle 4 adds
    revert-of-revert manual-recovery messaging. For now, subprocess and
    OSError exceptions propagate uncaught.
    """
    snap = snapshot_and_write(plan, repo_root=repo_root)
    run_install(snap)
    run_verify(snap)
    return ApplyResult(
        ok=True,
        snapshot_id=snap.snapshot_id,
        snapshot_dir=str(snap.snapshot_dir),
    )
