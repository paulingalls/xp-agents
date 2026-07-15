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
import sprint_status
import sprint_store

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


def worktree_path(name: str, cwd: str) -> Path:
    """Return the path to a worktree: {git_root}/{WORKTREE_PATH_FRAGMENT}{name}."""
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


def remove_worktree_dir(name: str, cwd: str, *, force: bool = True) -> str | None:
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
    """force_branch=True + unmerged -> dropped; caller MUST record it (story-003)."""


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


def _iter_live_teammate_worktrees(cwd: str):
    """Yield ``(worktree_path, branch)`` for non-prunable teammate
    worktrees that exist on disk.

    The porcelain output already carries each worktree's branch; emit
    both so callers don't have to re-spawn ``git -C <path> rev-parse``
    per worktree (was N subprocesses per /xp-story-close dispatch).

    Shared by has_live_teammates (boolean check),
    list_live_teammate_worktree_paths (story-id ⇄ path mapping),
    find_teammate_worktree_for_story (per-story lookup), and
    find_closing_teammate_worktree (path + branch lookup).
    """
    try:
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        return
    wt_marker = f"/{WORKTREE_PATH_FRAGMENT}{_WORKTREE_PREFIX}story-"
    for block in out.split("\n\n"):
        if "prunable" in block:
            continue
        wt_path = ""
        branch = ""
        for line in block.splitlines():
            if line.startswith("worktree ") and wt_marker in line:
                wt_path = line[len("worktree ") :]
            elif line.startswith("branch refs/heads/"):
                branch = line[len("branch refs/heads/") :]
        if wt_path and Path(wt_path).is_dir():
            yield wt_path, branch


def has_live_teammates(cwd: str) -> bool:
    """Return True if any non-prunable `worktree-story-*` worktree is registered.

    Uses `git worktree list --porcelain` so the check reflects real git
    state (not filesystem artifacts). Skips prunable entries — those are
    stale registrations whose directories no longer exist. Falls back to
    False when cwd is outside a git repo or the command fails.
    """
    # `_iter_live_teammate_worktrees` yields `(path, branch)` tuples;
    # any non-empty tuple is truthy, so iterator-yielding-anything IS
    # the existence signal — branch value is irrelevant here.
    return any(_iter_live_teammate_worktrees(cwd))


def list_live_teammate_worktree_paths(cwd: str) -> list[tuple[str, str]]:
    """Return ``(story_id, abs_path)`` for every live teammate worktree.

    /xp-accept needs the absolute path to ``cd`` into the story's
    worktree before running its acceptance command — the unmerged
    teammate edits live there, not in the orchestrator's HEAD.
    """
    # `_iter_live_teammate_worktrees` filters for paths under
    # `.claude/worktrees/worktree-story-*`, so every yielded basename
    # starts with `_WORKTREE_PREFIX` and the slice is unconditional.
    skip = len(_WORKTREE_PREFIX)
    return [
        (Path(wt_path).name[skip:], wt_path)
        for wt_path, _branch in _iter_live_teammate_worktrees(cwd)
    ]


def live_teammate_branch_by_story(cwd: str) -> dict[str, str]:
    """Map story_id → the BRANCH each live teammate worktree has checked out.

    The story-id half alone cannot identify a worktree, and every caller that
    treats it as if it could is answering a cross-sprint question with a
    within-sprint key. Story ids repeat every sprint, so
    `.claude/worktrees/worktree-story-003` may be LAST sprint's story-003, left
    registered after an abandoned close. The branch carries the slug
    (`<user>/story-003-perf-timers` vs `<user>/story-003-tools-remember`), so it
    is the only thing on the worktree that tells the two apart — the same
    argument `spawn_prompt.load_prompt_for_story` makes about the prompt file.

    An empty branch value means the worktree is on a detached HEAD (porcelain
    emits no `branch` line): not a match for any story, which is the safe
    direction for a caller deciding "is this story's teammate live?".
    """
    skip = len(_WORKTREE_PREFIX)
    return {
        Path(wt_path).name[skip:]: branch
        for wt_path, branch in _iter_live_teammate_worktrees(cwd)
    }


def find_closing_teammate_worktree(smm_dir: Path, cwd: str) -> tuple[str, str] | None:
    """Locate the teammate worktree corresponding to the in-closing story.

    Returns ``(abs_path, branch)`` for the live teammate worktree whose
    sprint.json story has ``status == "closing"`` — implicit-derivation
    discovery used by /xp-story-close to know which teammate worktree
    it's closing without requiring /xp-accept to pass context. Returns
    ``None`` when no live teammate worktree matches a closing story
    (solo flow, or no teammate currently mid-close).

    `closing` is the sprint-singleton in-pipeline state. /xp-accept
    promotes one reviewing story at a time to `closing` before
    dispatching /xp-story-close, so at most ONE closing-status story can
    have a live worktree at dispatch time. Two or more matches signals a
    broken iteration model — raise ValueError rather than guess which to
    close. `done` stories are excluded too (mark-done is the FINAL step
    after the close cycle).
    """
    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return None
    closing_ids = {
        s["id"] for s in sprint_status.select_closing_stories(sprint.get("stories", []))
    }
    skip = len(_WORKTREE_PREFIX)
    matches: list[tuple[str, str]] = []
    for wt_path, branch in _iter_live_teammate_worktrees(cwd):
        story_id = Path(wt_path).name[skip:]
        if story_id not in closing_ids:
            continue
        matches.append((wt_path, branch))
    if len(matches) > 1:
        ids = sorted(Path(p).name[skip:] for p, _ in matches)
        raise ValueError(
            "multiple closing stories with live teammate worktrees "
            f"({', '.join(ids)}); closing is the singleton lock — "
            "/xp-accept is expected to promote one reviewing story to "
            "closing at a time before dispatching /xp-story-close"
        )
    return matches[0] if matches else None


def resolve_own_teammate_worktree(cwd: str) -> tuple[str, str] | None:
    """Return ``(worktree_root, branch)`` when *cwd* is inside a teammate worktree.

    Invoker-identity detection: a teammate self-reviewing runs /xp-quality-review
    from its own ``.claude/worktrees/worktree-story-*`` tree, so its OWN cwd is
    the correct review target — not whatever story is ``closing`` in shared
    sprint state (the parallel-teammate closing-scan race). Pure cwd walk: no
    sprint.json read, no ``git worktree list`` scan — immune to that race.

    Returns ``None`` when *cwd* is the main checkout (orchestrator / solo).
    Keys on the same ``worktree-story-`` teammate prefix as
    ``identity.is_worktree_teammate`` (via ``is_teammate_agent_id``) so the two
    agree on what counts as a teammate worktree — a broader ``worktree-`` gate
    would bind the review to a non-teammate worktree the detector rejects.
    """
    name = identity.extract_worktree_name(cwd)
    if not name or not identity.is_teammate_agent_id(name):
        return None
    p = Path(cwd)
    root = next((anc for anc in (p, *p.parents) if anc.name == name), None)
    if root is None:
        return None
    return str(root), identity.get_current_branch(str(root))


def resolve_review_worktree(smm_dir: Path, cwd: str) -> tuple[str, str] | None:
    """Resolve the /xp-quality-review target worktree, invoker-identity first.

    Precedence (the testable seam guarding the parallel-teammate race): the
    invoker's OWN teammate worktree wins over the global closing-story scan.
    Only when the
    invoker is NOT inside a teammate worktree (the orchestrator) do we fall back
    to ``find_closing_teammate_worktree`` — unchanged behavior for that path.
    """
    own = resolve_own_teammate_worktree(cwd)
    if own is not None:
        return own
    return find_closing_teammate_worktree(smm_dir, cwd)


def branch_held_by_worktree(cwd: str, branch: str) -> bool:
    """True if any live worktree (registered in `git worktree list`) has
    `branch` checked out.

    /xp-story-close's Step 7 merge tries to delete the source branch
    after merge+push. For teammate stories the source branch is held by
    the teammate worktree, so `git branch -d` fails with "branch is
    checked out at <path>". This helper lets close_common.py detect the
    case and skip delete (cleanup_teammate.py owns deletion via
    worktree removal). Solo stories return False here — source isn't
    in any worktree by the time close_common.py reaches delete (the
    earlier _checkout_or_exit moved orchestrator off source).
    """
    try:
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):
        return False
    target_line = f"branch refs/heads/{branch}"
    return any(line == target_line for line in out.splitlines())


def find_teammate_worktree_for_story(story_id: str, cwd: str) -> str | None:
    """Return the worktree NAME (e.g. `worktree-story-042`) for a teammate
    that's working on `story_id`, or None if no live worktree matches.

    Powers /xp-story-close's Step 7b cleanup gate: solo mode has no
    matching worktree (returns None, cleanup skipped); teammate mode
    returns the exact name to pass as `cleanup_teammate.py --name`.
    Filters for exact `worktree-<story_id>` directory names — the
    naming convention defined in spawn_teammate.py + identity._TEAMMATE_PREFIX.
    """
    target = f"{_WORKTREE_PREFIX}{story_id}"
    for wt_path, _branch in _iter_live_teammate_worktrees(cwd):
        if Path(wt_path).name == target:
            return target
    return None


def teammate_report_path(smm_dir: Path, name: str) -> Path:
    """Return the path to a teammate's report file."""
    return smm_dir / marker_names.TEAMMATE_REPORT.format(name=name)


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
