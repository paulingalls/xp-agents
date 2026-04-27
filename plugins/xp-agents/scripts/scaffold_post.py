#!/usr/bin/env python3
"""Post-pipeline operations for /xp-scaffold-acceptance: commit + record.

Where ``scaffold_apply`` owns the fs/subprocess pipeline (write + install +
verify + atomic revert), this module owns the git/state side that runs
after a green verify:

- ``build_commit_message(...)``: pure formatter for the M-4 doctrine
  commit subject and trailers (Tool-version / Files-created /
  Files-modified / Verification / Resolves-Event).
- ``commit_scaffold(snap, ...)``: stage-aware branch + commit orchestration.
  Stage 0 commits on HEAD; Stage 1+ creates ``<user>/scaffold-<surface>``
  via ``branching.create_scaffold_branch`` and refuses commits to protected
  branches (main/master) when no scaffold branch is yet active.

Story-002 will add ``record_scaffold(...)`` here for the system_context
flip + concern-resolution decision event.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import branching
import identity
from scaffold_apply import ApplySnapshot


def build_commit_message(
    *,
    surface: str,
    tool: str,
    tool_version: str,
    verify_cmd: str,
    files_created: list[str],
    files_modified: list[str],
    concern_id: str | None,
) -> str:
    """Return the M-4 doctrine commit message string.

    Subject: ``[chore] Scaffold <surface> acceptance via <tool>``.
    Trailers (in order): ``Tool-version``, ``Files-created`` (omitted
    when empty), ``Files-modified`` (omitted when empty),
    ``Verification``, ``Resolves-Event`` — with ``Resolves-Event: none``
    when ``concern_id`` is None, per the SMM constraint that every
    commit body carry a Resolves-Event trailer.
    """
    subject = f"[chore] Scaffold {surface} acceptance via {tool}"
    trailers = [f"Tool-version: {tool_version}"]
    if files_created:
        trailers.append(f"Files-created: {', '.join(files_created)}")
    if files_modified:
        trailers.append(f"Files-modified: {', '.join(files_modified)}")
    trailers.append(f"Verification: {verify_cmd}")
    trailers.append(f"Resolves-Event: {concern_id or 'none'}")
    return subject + "\n\n" + "\n".join(trailers) + "\n"


@dataclass
class CommitResult:
    ok: bool
    sha: str | None = None
    branch: str | None = None
    reason: str | None = None


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)


def commit_scaffold(
    snap: ApplySnapshot,
    *,
    smm_dir: Path,
    stage: int,
    surface: str,
    tool: str,
    tool_version: str,
    concern_id: str | None,
) -> CommitResult:
    """Stage-aware branch + commit for a green scaffold.

    Stage 0: commit on the current HEAD with the doctrine subject.
    Stage 1+: refuse outright if HEAD is on a protected branch
    (main/master) — the user must check out a feature/scaffold branch
    first; otherwise create/checkout ``<user>/scaffold-<surface>`` via
    ``branching.create_scaffold_branch``. Refusal is deliberate even when
    a scaffold branch already exists locally: forcing an explicit user
    checkout off main avoids surprise branch switches mid-flow.
    Subprocess discipline mirrors ``scaffold_apply.run_install``: argv-only
    invocations, no shell metacharacter interpretation.
    """
    repo_root = snap.repo_root
    plan = snap.plan

    current_branch = identity.get_current_branch(str(repo_root))

    if branching.is_protected_branch(stage, current_branch):
        return CommitResult(
            ok=False,
            reason=(
                f"refuse to scaffold-commit on protected branch "
                f"{current_branch!r} at stage {stage}; create a scaffold "
                f"branch or move to a feature branch first"
            ),
        )

    target_branch = current_branch
    if stage >= 1:
        new_branch = branching.create_scaffold_branch(str(repo_root), surface, smm_dir)
        if new_branch is None:
            return CommitResult(
                ok=False,
                branch=current_branch,
                reason=f"branching gate skipped scaffold branch at stage {stage}",
            )
        target_branch = new_branch

    files_created = [e["path"] for e in plan.get("files_to_create", [])]
    files_modified = [e["path"] for e in plan.get("files_to_modify", [])]
    paths = files_created + files_modified

    if paths:
        add = _git(["git", "add", "--", *paths], repo_root)
        if add.returncode != 0:
            return CommitResult(
                ok=False,
                branch=target_branch,
                reason=f"git add failed: {add.stderr.strip()}",
            )

    msg = build_commit_message(
        surface=surface,
        tool=tool,
        tool_version=tool_version,
        verify_cmd=plan.get("verify_cmd", ""),
        files_created=files_created,
        files_modified=files_modified,
        concern_id=concern_id,
    )
    commit = _git(["git", "commit", "-m", msg], repo_root)
    if commit.returncode != 0:
        return CommitResult(
            ok=False,
            branch=target_branch,
            reason=f"git commit failed: {commit.stderr.strip()}",
        )

    sha = _git(["git", "rev-parse", "HEAD"], repo_root).stdout.strip()
    return CommitResult(ok=True, sha=sha, branch=target_branch)
