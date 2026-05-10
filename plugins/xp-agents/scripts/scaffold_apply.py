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
the skill provides is interpreted as argv, not a shell string. stdout
streams to ``snapshot_dir/<phase>.log`` (npm install / pip install -v
emit MBs of progress — file-streaming avoids in-memory buffering and
leaves the firehose available for inspection on failure); stderr stays
in-memory as PIPE for the brief reason summary. Timeouts: 300s install,
60s verify.
"""

import contextlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SnapshotState = Literal["cleaned", "retained", "none"]
Phase = Literal["write", "install", "verify-identity", "verify"]

sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import write_text_atomic  # noqa: E402

INSTALL_TIMEOUT_SEC = 300
VERIFY_TIMEOUT_SEC = 60
IDENTITY_VERIFY_TIMEOUT_SEC = 30
SNAPSHOT_PREFIX = "scaffold-snap-"
BACKUP_SUBDIR = "backup"
PLAN_FILE = "plan.json"

# Single source of truth for the cmd↔pattern coupling error — validate_plan
# is the only enforcer, but the message is referenced by tests too.
IDENTITY_PATTERN_REQUIRED_MSG = (
    "verify_identity_cmd set but expected_version_pattern is empty; "
    "either supply both or leave verify_identity_cmd empty to skip"
)


@dataclass
class ApplyResult:
    ok: bool
    snapshot_id: str | None = None
    snapshot_dir: str | None = None
    snapshot_state: SnapshotState = "none"
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

    def log_path(self, phase: str) -> Path:
        """Path to the streamed-stdout log for a given phase.

        Phases: ``install``, ``verify-identity``, ``verify``.
        """
        return self.snapshot_dir / f"{phase}.log"


def _new_snapshot_dir() -> tuple[str, Path]:
    snapshot_id = uuid.uuid4().hex[:12]
    snapshot_dir = Path(tempfile.gettempdir()) / f"{SNAPSHOT_PREFIX}{snapshot_id}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    (snapshot_dir / BACKUP_SUBDIR).mkdir()
    return snapshot_id, snapshot_dir


def validate_plan(plan: dict, *, repo_root: Path) -> str | None:
    """Return an error reason if the plan would silently corrupt customer
    state; ``None`` if safe to apply.

    Two symmetric guards:

    1. Every ``files_to_create`` entry must NOT already exist. ``revert()``
       blindly unlinks create-targets on failure; a misclassified existing
       file would be overwritten by write and deleted on revert.
    2. Every ``files_to_modify`` entry MUST already exist. ``create_snapshot``
       suppresses ``FileNotFoundError`` when backing up a missing target;
       ``write_files`` then creates the file fresh, and ``revert()`` cannot
       restore a backup that was never taken — the file orphans.

    Create-side violations win when both are present: the create case is
    higher-impact (data loss vs orphan file) so its message surfaces first.
    """
    collisions = [
        entry["path"]
        for entry in plan.get("files_to_create", [])
        if (repo_root / entry["path"]).exists()
    ]
    if collisions:
        paths = ", ".join(collisions)
        return (
            "files_to_create entries already exist in repo_root: "
            f"{paths}. These look like modifications — move them to "
            "files_to_modify (with full merged body) or remove them from "
            "the plan. Refusing to overwrite pre-existing customer files."
        )
    missing = [
        entry["path"]
        for entry in plan.get("files_to_modify", [])
        if not (repo_root / entry["path"]).exists()
    ]
    if missing:
        paths = ", ".join(missing)
        return (
            "files_to_modify entries do not exist in repo_root: "
            f"{paths}. These look like new files — move them to "
            "files_to_create or remove them from the plan. Refusing to "
            "create files via the modify path (no backup means no revert)."
        )
    if plan.get("verify_identity_cmd") and not plan.get("expected_version_pattern"):
        return IDENTITY_PATTERN_REQUIRED_MSG
    return None


def load_snapshot(snapshot_id: str, *, repo_root: Path) -> ApplySnapshot:
    """Re-load a snapshot for the cycle-5 CLI.

    Reads ``${TMPDIR}/scaffold-snap-<id>/plan.json``. Raises
    FileNotFoundError when the snapshot directory or plan.json is gone
    (e.g., the temp dir was already cleaned up).
    """
    snapshot_dir = Path(tempfile.gettempdir()) / f"{SNAPSHOT_PREFIX}{snapshot_id}"
    plan = json.loads((snapshot_dir / PLAN_FILE).read_text(encoding="utf-8"))
    return ApplySnapshot(
        snapshot_id=snapshot_id,
        snapshot_dir=snapshot_dir,
        repo_root=repo_root,
        plan=plan,
    )


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
    """Run each install_cmds entry in repo_root.

    stdout streams to ``snapshot_dir/install.log`` (npm/pip/jest emit
    multi-MB on failure — file-streaming avoids in-memory buffering and
    leaves the firehose available for inspection). stderr stays captured
    in-memory so ``CalledProcessError.stderr`` carries the brief summary
    that goes into ApplyResult.reason. Multiple install_cmds append to
    the same log so the ordering is preserved.

    Raises CalledProcessError or TimeoutExpired on failure.
    """
    log_path = snap.log_path("install")
    with log_path.open("ab") as logf:
        for cmd in snap.plan.get("install_cmds", []):
            subprocess.run(
                shlex.split(cmd),
                cwd=snap.repo_root,
                check=True,
                timeout=INSTALL_TIMEOUT_SEC,
                stdout=logf,
                stderr=subprocess.PIPE,
                text=True,
            )


def run_verify_identity(snap: ApplySnapshot) -> None:
    """Run verify_identity_cmd and assert stdout matches expected_version_pattern.

    A successful ``install_cmds`` can still land the wrong binary —
    e.g. ``brew install --cask <name>`` lands an unrelated GUI app
    when the formula and cask share a name. Between install and verify,
    invoke the tool's ``--version`` (or equivalent) and use ``re.search``
    against ``expected_version_pattern``. Mismatch raises
    ``CalledProcessError`` so apply_plan's revert path engages — same
    failure shape as a non-zero install.

    Skipped (no-op) when ``verify_identity_cmd`` is empty (back-compat
    for plans built before the identity probe existed). The cmd↔pattern
    coupling (cmd set ⇒ pattern required) is enforced by ``validate_plan``
    pre-snapshot — direct callers must run plans through ``apply_plan`` /
    ``validate_plan`` first. stdout is captured in-memory (``--version``
    payload is small) and then mirrored to ``snapshot_dir/verify-identity.log``
    so failure diagnostics carry a log-pointer symmetric with install/verify;
    stderr stays in-memory for the failure summary.
    """
    cmd = snap.plan.get("verify_identity_cmd")
    pattern = snap.plan.get("expected_version_pattern", "")
    if not cmd:
        return
    # Defense-in-depth: validate_plan pre-checks, but re.search("", stdout)
    # matches everything — fail fast if a future caller bypasses validation.
    if not pattern:
        raise ValueError(IDENTITY_PATTERN_REQUIRED_MSG)
    completed = subprocess.run(
        shlex.split(cmd),
        cwd=snap.repo_root,
        check=True,
        timeout=IDENTITY_VERIFY_TIMEOUT_SEC,
        capture_output=True,
        text=True,
    )
    snap.log_path("verify-identity").write_text(completed.stdout, encoding="utf-8")
    if not re.search(pattern, completed.stdout):
        first_line = (completed.stdout.splitlines() or [""])[0][:120]
        raise subprocess.CalledProcessError(
            1,
            cmd,
            output=completed.stdout,
            stderr=(
                f"identity mismatch: pattern {pattern!r} did not match "
                f"--version output {first_line!r}"
            ),
        )


def run_verify(snap: ApplySnapshot) -> None:
    """Run verify_cmd in repo_root, streaming stdout to verify.log.

    Same stdout-to-log + stderr-to-PIPE pattern as run_install. Raises
    CalledProcessError or TimeoutExpired on non-zero / timeout.
    """
    cmd = snap.plan.get("verify_cmd")
    if not cmd:
        return
    log_path = snap.log_path("verify")
    with log_path.open("ab") as logf:
        subprocess.run(
            shlex.split(cmd),
            cwd=snap.repo_root,
            check=True,
            timeout=VERIFY_TIMEOUT_SEC,
            stdout=logf,
            stderr=subprocess.PIPE,
            text=True,
        )


def cleanup_snapshot(snap: ApplySnapshot) -> None:
    """Remove the on-disk snapshot directory.

    Call only on success paths: apply_plan ok=True, apply-verify ok=True,
    apply-revert with unrestored=[]. Failure paths retain the snapshot —
    the reason field points at the per-phase log file for customer
    inspection, and the recovery message (when revert itself fails)
    names the snapshot dir + unrestored paths. Cleaning up on failure
    would invalidate both pointers. ``ignore_errors=True`` since the dir
    is process-local under TMPDIR — partial cleanup is fine.
    """
    shutil.rmtree(snap.snapshot_dir, ignore_errors=True)


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


def phase_failure_reason(
    exc: BaseException, *, timeout_sec: int, log_path: Path | None = None
) -> str:
    """Format a failure reason from a subprocess exception.

    Brief stderr summary first; when ``log_path`` is provided, append a
    hint pointing the customer at the full stdout firehose for the failed
    phase.
    """
    if isinstance(exc, subprocess.TimeoutExpired):
        head = f"timeout after {timeout_sec}s"
    else:
        stderr = getattr(exc, "stderr", "") or ""
        head = stderr.strip() or str(exc)
    if log_path is not None:
        return f"{head}\n(see {log_path} for full output)"
    return head


def failure_result(phase: str, reason: str, snap: ApplySnapshot) -> ApplyResult:
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
        snapshot_state="retained",
        recovery=recovery,
    )


def apply_write_only(
    plan: dict, *, repo_root: Path
) -> tuple[ApplyResult, ApplySnapshot | None]:
    """Validate the plan, create snapshot, write all bodies.

    Returns ``(result, snap)``. On success, ``result.ok=True`` and
    ``snap`` is non-None — caller can run install/verify against it. On
    validation failure ``snap`` is None; on write failure ``snap`` is the
    rolled-back snapshot. Both ``apply_plan`` and the CLI ``apply-write``
    subcommand drive this helper to keep the validate→snapshot→write
    prefix in one place.
    """
    invalid_reason = validate_plan(plan, repo_root=repo_root)
    if invalid_reason is not None:
        return (
            ApplyResult(ok=False, phase="write", reason=invalid_reason),
            None,
        )
    snap = create_snapshot(plan, repo_root=repo_root)
    try:
        write_files(snap)
    except OSError as exc:
        return (failure_result("write", str(exc), snap), snap)
    return (
        ApplyResult(
            ok=True,
            snapshot_id=snap.snapshot_id,
            snapshot_dir=str(snap.snapshot_dir),
            snapshot_state="retained",
        ),
        snap,
    )


def apply_plan(plan: dict, *, repo_root: Path) -> ApplyResult:
    """Drive write → install → verify; auto-revert the snapshot on any failure."""
    write_result, snap = apply_write_only(plan, repo_root=repo_root)
    if not write_result.ok or snap is None:
        return write_result
    try:
        run_install(snap)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return failure_result(
            "install",
            phase_failure_reason(
                exc,
                timeout_sec=INSTALL_TIMEOUT_SEC,
                log_path=snap.log_path("install"),
            ),
            snap,
        )
    try:
        run_verify_identity(snap)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return failure_result(
            "verify-identity",
            phase_failure_reason(
                exc,
                timeout_sec=IDENTITY_VERIFY_TIMEOUT_SEC,
                log_path=snap.log_path("verify-identity"),
            ),
            snap,
        )
    try:
        run_verify(snap)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return failure_result(
            "verify",
            phase_failure_reason(
                exc,
                timeout_sec=VERIFY_TIMEOUT_SEC,
                log_path=snap.log_path("verify"),
            ),
            snap,
        )
    snapshot_id = snap.snapshot_id
    cleanup_snapshot(snap)
    return ApplyResult(
        ok=True, snapshot_id=snapshot_id, snapshot_dir=None, snapshot_state="cleaned"
    )
