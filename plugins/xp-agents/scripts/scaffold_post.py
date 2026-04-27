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
- ``record_scaffold(snap, ...)``: flips the matching
  ``acceptance_surfaces[*].status`` to ``"covered"`` and stamps the
  verify command onto ``acceptance_template_command`` for downstream
  capstone-story reuse (xp-sprint-start). When a non-sentinel
  ``concern_id`` is supplied, also appends a ``decision`` event with
  ``metadata.resolves=[concern_id]`` (STRONG link) so the
  missing-acceptance concern that motivated the scaffold cascades
  closed.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

import _common
import branching
import identity
import system_context_store
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
    category: str = "acceptance",
) -> str:
    """Return the M-4 doctrine commit message string.

    Subject: ``[chore] Scaffold <category> <surface> via <tool>`` —
    3-slot per scaffolding doctrine §Commit Strategy. ``category``
    defaults to ``"acceptance"`` for the M-4 acceptance-only flow;
    future categories (contract, chaos, …) slot in without renaming.

    Trailers (in order): ``Tool-version``, ``Files-created`` (omitted
    when empty), ``Files-modified`` (omitted when empty),
    ``Verification``, ``Resolves-Event`` — with ``Resolves-Event: none``
    when ``concern_id`` is None, per the SMM constraint that every
    commit body carry a Resolves-Event trailer.
    """
    subject = f"[chore] Scaffold {category} {surface} via {tool}"
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


@dataclass
class RecordResult:
    ok: bool
    reason: str | None = None
    decision_event_id: str | None = None


def record_scaffold(
    snap: ApplySnapshot,
    *,
    smm_dir: Path,
    surface: str,
    verify_cmd: str,
    concern_id: str | None,
    agent_id: str,
    commit_sha: str | None = None,
) -> RecordResult:
    """Flip ``acceptance_surfaces[<surface>].status`` to ``"covered"``.

    Reads ``system_context.json`` via ``system_context_store.load_system_context``,
    finds the surface entry by name, sets ``status="covered"`` and
    ``acceptance_template_command=verify_cmd``, and writes the document
    back via ``system_context_store.save_system_context`` (atomic write +
    schema validation). Other surface entries and their fields are
    untouched.

    When ``commit_sha`` is supplied, verifies via ``git cat-file -e`` that
    the sha exists in ``snap.repo_root`` BEFORE the surface flip. Closes
    the atomicity gap where ``apply-record`` could flip a surface to
    covered even when ``apply-commit`` produced no commit on disk —
    state would lie. ``RecordResult(ok=False, reason=...)`` short-circuits
    when the sha is missing.

    When ``concern_id`` is a 12-hex event ID (not None and not the
    sentinel ``"none"``), also appends a ``decision`` event with
    ``metadata.resolves=[concern_id]``, ``metadata.snapshot_id`` (from
    ``snap.snapshot_id``) and (when supplied) ``metadata.commit_sha`` for
    provenance. The new event's id is returned in
    ``RecordResult.decision_event_id``.

    Returns ``RecordResult(ok=False, reason=...)`` when the system_context
    document is missing, when the named surface is missing, when the
    expected commit_sha is absent from the repo, or when the post-mutation
    save fails schema validation.
    """
    if commit_sha:
        check = subprocess.run(
            ["git", "cat-file", "-e", commit_sha],
            cwd=snap.repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if check.returncode != 0:
            return RecordResult(
                ok=False,
                reason=(
                    f"expected scaffold commit {commit_sha!r} not found in "
                    f"{snap.repo_root}; refuse to flip surface to covered "
                    "without the commit landed"
                ),
            )
    ctx = system_context_store.load_system_context(smm_dir)
    if ctx is None:
        return RecordResult(
            ok=False,
            reason=(
                "system_context.json not found; run /xp-system-context "
                "before scaffolding"
            ),
        )
    surfaces = ctx.get("acceptance_surfaces", [])
    target = next((s for s in surfaces if s.get("name") == surface), None)
    if target is None:
        return RecordResult(
            ok=False,
            reason=(
                f"surface {surface!r} not found in acceptance_surfaces; "
                "run /xp-system-context to record it before scaffolding"
            ),
        )
    target["status"] = "covered"
    target["acceptance_template_command"] = verify_cmd
    try:
        system_context_store.save_system_context(smm_dir, ctx)
    except (ValueError, OSError) as exc:
        return RecordResult(
            ok=False,
            reason=f"system_context save failed: {exc}",
        )

    decision_event_id: str | None = None
    if concern_id and concern_id != "none":
        metadata: dict = {"resolves": [concern_id], "snapshot_id": snap.snapshot_id}
        if commit_sha:
            metadata["commit_sha"] = commit_sha
        event = _common.make_event(
            "decision",
            agent_id,
            f"Acceptance surface {surface!r} covered via /xp-scaffold-acceptance",
            topic=f"scaffold-acceptance-{surface}",
            metadata=metadata,
        )
        _common.append_safe(smm_dir, event)
        decision_event_id = event["id"]

    return RecordResult(ok=True, decision_event_id=decision_event_id)
