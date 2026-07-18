#!/usr/bin/env python3
"""Install / identity-verify / verify phase group for /xp-scaffold-acceptance.

Split out of scaffold_apply.py to keep modules focused on a single
responsibility (see CLAUDE.md "Keep files small and focused"). ``apply_plan``
in scaffold_apply.py orchestrates these phases in sequence and imports them
back by identity, so ``scaffold_apply.run_install is scaffold_verify.run_install``
(and likewise for the other moved names) — every existing import site and
``mock.patch`` target keeps working unedited.

Subprocess discipline: install/verify run with ``shell=False``; commands are
split via ``shlex.split`` so the canonical / web-refreshed knowledge the
skill provides is interpreted as argv, not a shell string. stdout streams to
``snapshot_dir/<phase>.log`` (npm install / pip install -v emit MBs of
progress — file-streaming avoids in-memory buffering and leaves the firehose
available for inspection on failure); stderr stays in-memory as PIPE for the
brief reason summary. Timeouts: 300s install, 60s verify, 30s identity-verify.
"""

import re
import shlex
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scaffold_apply import ApplySnapshot

INSTALL_TIMEOUT_SEC = 300
VERIFY_TIMEOUT_SEC = 60
IDENTITY_VERIFY_TIMEOUT_SEC = 30

# Single source of truth for the cmd↔pattern coupling error — validate_plan
# (in scaffold_apply.py) is the only enforcer, but the message is referenced
# by run_verify_identity below and by tests too.
IDENTITY_PATTERN_REQUIRED_MSG = (
    "verify_identity_cmd set but expected_version_pattern is empty; "
    "either supply both or leave verify_identity_cmd empty to skip"
)


def run_install(snap: "ApplySnapshot") -> None:
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


def run_verify_identity(snap: "ApplySnapshot") -> None:
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


def run_verify(snap: "ApplySnapshot") -> None:
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
