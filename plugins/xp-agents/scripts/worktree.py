#!/usr/bin/env python3
"""Git worktree and path management utilities.

Provides worktree path resolution, creation/removal, teammate report paths,
and project-relative path normalization. All operations share a cached
git root resolution to avoid redundant subprocess calls.
"""

import enum
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import branch_lifecycle
import identity
import marker_names
import worktree_teardown

_WORKTREE_PREFIX = "worktree-"

# Re-export the shared worktree-path constant from identity.py (its lower
# position in the import chain avoids a worktree↔identity cycle). The
# canonical home is identity.py; this re-export keeps callers like
# `worktree.WORKTREE_PATH_FRAGMENT` working when the natural module is
# the one named after the concept.
WORKTREE_PATH_FRAGMENT = identity.WORKTREE_PATH_FRAGMENT

_git_root_cache: dict[str, str | None] = {}


def resolve_git_root(cwd: str) -> str | None:
    """Return the git working tree root for the given cwd. Cached per cwd."""
    if cwd in _git_root_cache:
        return _git_root_cache[cwd]
    try:
        root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
        ).strip()
    # OSError, not just the two subclasses this used to name. Every caller
    # already handles None (they degrade to cwd/absolute paths), but an
    # exception ESCAPING here does not block — it kills the hook with a
    # traceback, and PreToolUse reads a non-2 exit as a non-blocking error, so
    # the Write it sits under is waved through un-gated. A fail-open, from the
    # bottom of the one path that must fail closed. FileNotFoundError and
    # NotADirectoryError are OSError subclasses, so this only widens.
    except (subprocess.CalledProcessError, OSError):
        root = None
    _git_root_cache[cwd] = root
    return root


def _clear_git_root_cache() -> None:
    """Clear the git root cache. For testing only."""
    _git_root_cache.clear()


def _out_of_repo_worktrees_base() -> Path | None:
    """{base}/{project-id}/worktrees (sibling of the SMM dir) or None.

    resolve_smm_dir() returns `{base}/{project-id}/smm`, the invariant
    teammate_runner._project_dir already trusts, so `.parent` is the project
    dir. Returns None when the SMM dir can't be resolved or resolving it raises,
    signalling worktree_path to fall back to the legacy in-repo placement.
    """
    from _append_impl import resolve_smm_dir  # deferred function-level import

    smm = resolve_smm_dir()
    if smm is None:
        return None
    try:
        return Path(smm).resolve().parent / "worktrees"
    except OSError:
        return None


def worktree_path(name: str, cwd: str) -> Path:
    """Return the path to a worktree, out of the repo when possible.

    Placement is `{base}/{project-id}/worktrees/{name}` — a sibling of the SMM
    dir, OUT of the repo. Outside the primary checkout, a Node module walk-up
    from the worktree never reaches the primary's node_modules, so an
    un-provisioned dependency yields an honest MODULE_NOT_FOUND (the measured
    dependency-resolution leak, story-024). Both create and remove funnel
    through here, so they stay consistent for free.
    """
    base = _out_of_repo_worktrees_base()
    if base is not None:
        return base / name
    # LEGACY IN-REPO FALLBACK: {git_root}/.claude/worktrees/{name}. Fires only
    # when the out-of-repo base is unresolvable (no SMM data root available);
    # a documented safe degradation, never a crash (AC3).
    root = resolve_git_root(cwd)
    if not root:
        raise RuntimeError(f"Not a git repository: {cwd}")
    return Path(root) / WORKTREE_PATH_FRAGMENT / name


class WorktreeNotEmpty(Exception):
    """A worktree could not be removed without destroying uncommitted work.

    Raised only by ``remove_worktree_dir(force=False)``. Refusing is the point:
    the alternative is `git worktree remove --force`, which deletes the tree —
    modified files, untracked files and all. When the worktree belongs to a
    teammate that is still RUNNING, that is its in-flight story; when it belongs
    to one that crashed, it is the only copy of work that was never committed.
    Neither is ours to throw away, and a loud refusal is recoverable (inspect it,
    commit or discard, re-run) where a silent delete is not.
    """


def remove_worktree_dir(
    name: str, cwd: str, *, force: bool = True, smm_dir: Path | None = None
) -> str | None:
    """Remove the worktree DIRECTORY and prune stale entries. Delete NO branch.

    Returns the branch the worktree had checked out — the caller cannot re-read
    it afterwards, because the HEAD it is derived from goes away with the
    directory. None means there was nothing to work with (not a git repo).

    The worktree DIR name and the BRANCH name diverge in production: /xp-assign
    creates worktrees named `worktree-story-NNN` checked out to branches like
    `<user>/story-NNN-<slug>`. Falling back to `name` when derivation fails
    preserves the legacy contract for callers that create worktree + branch
    with the same name (`spawn_teammate.create_worktree` in no-branch mode).

    *force* is the caller's claim about who owns the tree, and the two callers
    genuinely differ:

      - True (post-merge cleanup): the story is merged and done, so build
        artifacts and stray files are debris — `--force` is what clears them.
      - False (`spawn_teammate.cleanup_existing` clearing the path for a
        re-spawn): the tree may belong to a teammate that is STILL RUNNING, and
        `--force` would delete its uncommitted work out from under it. Git's own
        non-force refusal ("contains modified or untracked files") is the signal
        we want, so let it refuse and raise WorktreeNotEmpty rather than
        overriding it. A crashed teammate's un-committed work is protected by the
        same refusal, which is the other half of what makes it right.

    *smm_dir*, when given together with force=True, runs the project's
    declared `stack.worktree_teardown` command against the worktree BEFORE
    removal. force=False is excluded — that caller (the re-spawn path) may
    be looking at a tree a live peer still owns, and tearing down its stack
    out from under it would stop a running service and leave the peer's own
    removal refused with the stack already dead. `worktree_path(name, cwd)`
    is used only inside the `wt.is_dir()` branch below, so run_teardown's
    unvalidated `wt_path` precondition holds by construction.
    """
    try:
        wt = worktree_path(name, cwd)
    except RuntimeError:
        return None
    branch = name
    if wt.is_dir():
        # `identity.get_current_branch` returns "" on failure and "HEAD"
        # for detached HEAD (mid-rebase / mid-bisect / `git checkout <sha>`).
        # Either way the `name` fallback preserves legacy behavior for
        # tests that create worktree + branch with the same name.
        head = identity.get_current_branch(str(wt))
        if head and head != "HEAD":
            branch = head

        if smm_dir is not None and force:
            worktree_teardown.run_teardown(str(wt), smm_dir)

        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        result = subprocess.run(
            [*cmd, str(wt)],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if not force and result.returncode != 0 and wt.is_dir():
            raise WorktreeNotEmpty(
                f"refusing to clear the worktree at {wt}: git will not remove it "
                f"({result.stderr.strip() or 'non-zero exit'}). It holds modified "
                "or untracked files — a teammate is either still working there or "
                "crashed before committing, and forcing the removal would destroy "
                "that work. Inspect it, commit or discard the changes, remove the "
                "worktree by hand, then re-run."
            )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=cwd,
        capture_output=True,
    )
    return branch


class BranchRemoval(enum.Enum):
    """What remove_worktree did to the worktree's branch."""

    NO_BRANCH = "no_branch"
    """Nothing to delete (not a git repo / no worktree)."""

    DELETED_MERGED = "deleted_merged"
    """delete_branch proved merge into merge_target; branch is gone."""

    REFUSED_UNMERGED = "refused_unmerged"
    """Not provably merged, force_branch=False -> branch kept (loud, no data loss)."""

    FORCE_DROPPED_UNMERGED = "force_dropped_unmerged"
    """force_branch=True + unmerged -> dropped. Reached only by spawn_teammate's
    re-spawn cleanup, which force-drops a throwaway worktree-name branch (never a
    story's recorded branch); the outcome is informational and current callers
    ignore it. See the "one crack" note in story_done_gate."""


def remove_worktree(
    name: str, cwd: str, *, merge_target: str | None = None, force_branch: bool = False
) -> BranchRemoval:
    """Remove a git worktree directory, prune, AND delete its branch.

    For callers that OWN the branch — it was cut for this worktree and dies
    with it. A caller that is merely clearing the directory (so it can re-add a
    worktree onto a branch someone else owns) must call ``remove_worktree_dir``
    instead: a force-drop here force-deletes whatever the worktree had checked
    out, unmerged commits included.

    Branch deletion is routed through ``branch_lifecycle.delete_branch``, which
    proves the branch is merged into ``merge_target`` (or HEAD, when omitted)
    before deleting — never trusts `git branch -d`'s own upstream-based proof.
    When the proof fails, an unmerged branch is either refused (kept, loud) or
    force-dropped, and the caller learns which via the returned ``BranchRemoval``.
    """
    branch_to_delete = remove_worktree_dir(name, cwd)
    if branch_to_delete is None:
        return BranchRemoval.NO_BRANCH
    if branch_lifecycle.delete_branch(cwd, branch_to_delete, merge_target=merge_target):
        return BranchRemoval.DELETED_MERGED
    if not force_branch:
        return BranchRemoval.REFUSED_UNMERGED
    subprocess.run(
        ["git", "branch", "-D", branch_to_delete],
        cwd=cwd,
        capture_output=True,
    )
    return BranchRemoval.FORCE_DROPPED_UNMERGED


# Teammate-worktree discovery/query helpers, split into
# worktree_discovery.py when worktree.py crossed the 500-line ceiling.
# `worktree.<name>` stays the read surface for every existing importer and
# `mock.patch("...worktree.X")` site — identity re-export, same pattern as
# the in_place_marker re-export below.
from worktree_discovery import (  # noqa: E402, F401
    _iter_live_teammate_worktrees,
    branch_held_by_worktree,
    find_closing_teammate_worktree,
    find_teammate_worktree_for_story,
    has_live_teammates,
    list_live_teammate_worktree_paths,
    live_teammate_branch_by_story,
    resolve_own_teammate_worktree,
)


def resolve_review_worktree(smm_dir: Path, cwd: str) -> tuple[str, str] | None:
    """Resolve the /xp-quality-review target worktree, invoker-identity first.

    Precedence (the testable seam guarding the parallel-teammate race): the
    invoker's OWN teammate worktree wins over the global closing-story scan.
    Only when the
    invoker is NOT inside a teammate worktree (the orchestrator) do we fall back
    to ``find_closing_teammate_worktree`` — unchanged behavior for that path.

    Kept in this module (not worktree_discovery) so the ``worktree.``-qualified
    ``mock.patch`` of ``find_closing_teammate_worktree`` in the review-target
    tests still intercepts the call below via this module's namespace.
    """
    own = resolve_own_teammate_worktree(cwd)
    if own is not None:
        return own
    return find_closing_teammate_worktree(smm_dir, cwd)


def teammate_report_path(smm_dir: Path, name: str) -> Path:
    """Return the path to a teammate's report file."""
    return smm_dir / marker_names.TEAMMATE_REPORT.format(name=name)


def teammate_stream_dump_path(smm_dir: Path, name: str) -> Path:
    """Return the path to a teammate's captured-stream diagnostic dump."""
    return smm_dir / marker_names.TEAMMATE_STREAM_DUMP.format(name=name)


def write_teammate_stream_dump(smm_dir: Path, name: str, text: str) -> Path:
    """Atomically write the stream dump file with symlink rejection.

    *text* arrives already composed (header + retained lines) — this
    function only owns the path and the write, mirroring
    write_story_assignment. Returns the path written, so a caller that
    reports it never re-derives (and cannot name a path it did not write).
    """
    from _append_impl import write_text_atomic

    path = teammate_stream_dump_path(smm_dir, name)
    if path.is_symlink():
        raise OSError(f"Refusing to write to symlink: {path}")
    write_text_atomic(path, text)
    return path


def story_assignment_path(smm_dir: Path, name: str) -> Path:
    """Return the path to a teammate's story assignment file."""
    return smm_dir / marker_names.STORY_ASSIGNMENT.format(name=name)


def write_story_assignment(smm_dir: Path, name: str, story_id: str) -> None:
    """Atomically write story assignment marker with symlink rejection."""
    from _append_impl import write_text_atomic

    path = story_assignment_path(smm_dir, name)
    if path.is_symlink():
        raise OSError(f"Refusing to write to symlink: {path}")
    write_text_atomic(path, story_id)


# Back-compat re-exports for the in-place teammate marker (presence + liveness),
# split into in_place_marker.py when worktree.py crossed the 500-line ceiling.
# `worktree.<name>` stays the read surface for identity, pre_tool_skill,
# commit_event and sprint_stop_gate. spawn_teammate — the marker's only writer
# and only deleter — imports in_place_marker directly.
#
# Liveness is a LOCK, not a pid: the supervisor holds a per-name flock for the
# whole episode and the kernel releases it however that process dies, OR'd with
# the recorded child pid (the `claude` child outlives a SIGKILLed supervisor).
# See in_place_marker / in_place_locks.
#
# Every name here is guarded, and there is deliberately no unguarded sibling of
# any of them — an "unlink it whoever wrote it" or "write it whatever is there"
# helper would sit next to the guarded one as the obvious thing to reach for, and
# either one deletes a same-name respawn's LIVE marker. So:
#   claim_in_place_marker       — takes the name exclusively, or refuses
#   rewrite_own_in_place_marker — rewrites only while we HOLD the name
#   remove_own_in_place_marker  — unlinks only while we HOLD the name
from in_place_marker import (  # noqa: E402, F401
    InPlaceNameHeld,
    claim_in_place_marker,
    has_live_in_place_teammate,
    in_place_marker_exists,
    in_place_marker_path,
    in_place_teammate_from_env,
    remove_own_in_place_marker,
    rewrite_own_in_place_marker,
)


def normalize_path(file_path: str, cwd: str) -> str:
    """Resolve a file path against cwd, return project-relative string.

    Returns a path relative to git root (e.g. 'src/app.ts') for shorter
    events and worktree-safe coordination. Falls back to absolute path
    when git root is unavailable or path is outside the repo.
    """
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(cwd) / p
    full = str(p)
    resolved = os.path.realpath(full)
    absolute = resolved if os.path.exists(resolved) else os.path.normpath(full)

    git_root = resolve_git_root(cwd)
    if git_root:
        prefix = os.path.realpath(git_root).rstrip("/") + "/"
        if absolute.startswith(prefix):
            return absolute[len(prefix) :]
        if not os.path.exists(full):
            cur = full
            tail_parts: list[str] = []
            while cur and not os.path.exists(cur):
                cur, tail = os.path.split(cur)
                if not tail:
                    break
                tail_parts.append(tail)
            if cur and os.path.exists(cur):
                resolved_ancestor = os.path.realpath(cur)
                for part in reversed(tail_parts):
                    resolved_ancestor = os.path.join(resolved_ancestor, part)
                if resolved_ancestor.startswith(prefix):
                    return resolved_ancestor[len(prefix) :]
    return absolute
