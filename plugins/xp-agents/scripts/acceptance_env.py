#!/usr/bin/env python3
"""Serial main-checkout acceptance mechanics (Mechanism A).

Point the provisioned main checkout at a teammate story's tip for acceptance,
then restore. Installed deps are gitignored, so swapping the main working
tree's *tracked* files to the story tip leaves node_modules/.venv intact — the
harness runs provisioned. Mechanism A is a detached-HEAD checkout of the story
tip (never ``checkout <branch>``: the branch is held by the teammate worktree,
so git refuses a second checkout of it).

Pure library — no CLI (that is branching_cli's job) and no /xp-accept wiring
(Milestone 2). Reuses the public helpers in branching/worktree/identity; the
local ``_git`` mirrors the branch_lifecycle.py import-isolation precedent.
"""

import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import branching
import identity
import worktree


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=10)


def _tip_of_worktree(story_id: str, wt_path: str) -> str:
    """Return the worktree's HEAD commit SHA; raise on a git failure."""
    r = _git(["git", "rev-parse", "HEAD"], wt_path)
    if r.returncode != 0:
        raise ValueError(
            f"cannot resolve tip of {story_id} worktree: {r.stderr.strip()}"
        )
    return r.stdout.strip()


def resolve_story_tip(smm_dir: Path, cwd: str, story_id: str) -> tuple[str, str]:
    """Return ``(tip_sha, restore_ref)`` for a live teammate story.

    ``tip_sha`` is the story worktree's HEAD commit; ``restore_ref`` is the
    sprint base branch (``branching.get_story_base_branch``). Raises
    ValueError when no live teammate worktree matches ``story_id`` — callers
    only resolve stories already known to be in TEAMMATE_WORKTREES, so a miss
    is a broken state, not a normal path (the _required fail-loud convention).
    """
    wt_path = next(
        (
            path
            for sid, path in worktree.list_live_teammate_worktree_paths(cwd)
            if sid == story_id
        ),
        None,
    )
    if wt_path is None:
        raise ValueError(f"no live teammate worktree for {story_id}")
    return (
        _tip_of_worktree(story_id, wt_path),
        branching.get_story_base_branch(smm_dir, cwd),
    )


def checkout_story_tip(cwd: str, tip_sha: str) -> None:
    """Detach the main checkout onto ``tip_sha``; refuse on a dirty tree.

    ``checkout --detach`` (never a branch checkout): the story branch is held
    by the teammate worktree, so git would refuse a second checkout. Refusing
    on a dirty tree leaves the working tree untouched.
    """
    if not branching.is_worktree_clean(cwd):
        raise ValueError("refusing to checkout story tip: main working tree is dirty")
    r = _git(["git", "checkout", "--detach", tip_sha], cwd)
    if r.returncode != 0:
        raise ValueError(f"checkout --detach {tip_sha} failed: {r.stderr.strip()}")


def restore(cwd: str, restore_ref: str) -> None:
    """Return the main checkout to ``restore_ref``. Mandatory after acceptance."""
    r = _git(["git", "checkout", restore_ref], cwd)
    if r.returncode != 0:
        raise ValueError(f"restore checkout {restore_ref} failed: {r.stderr.strip()}")


def detect_interrupted(cwd: str) -> str | None:
    """Classify a leftover interrupted state from a crashed acceptance run.

    ``"in-progress-merge"`` (MERGE_HEAD present) takes precedence over
    ``"detached-HEAD"`` (``get_current_branch`` returns the literal
    ``"HEAD"``); None when on a normal branch. Tests ``== "HEAD"``, not
    truthiness — ``get_current_branch`` also returns ``""`` on git failure.

    The merge probe is ``identity.merge_in_progress``, not a local one. This
    module keeps a local ``_git`` per the branch_lifecycle import-isolation
    precedent, but a SECOND merge detector is a different thing from an isolated
    subprocess helper: the schedule gate reads the same fact to exempt a write,
    and two copies would let the two disagree about one repo.
    """
    if identity.merge_in_progress(cwd):
        return "in-progress-merge"
    if identity.get_current_branch(cwd) == "HEAD":
        return "detached-HEAD"
    return None


def recover(smm_dir: Path, cwd: str) -> str | None:
    """Heal an interrupted main checkout before a fresh accept run.

    Aborts an in-progress merge, then restores to the story base branch.
    Returns the recovered-state description, or None when nothing needed.
    """
    state = detect_interrupted(cwd)
    if state is None:
        return None
    if identity.merge_in_progress(cwd):
        r = _git(["git", "merge", "--abort"], cwd)
        if r.returncode != 0:
            raise ValueError(f"git merge --abort failed: {r.stderr.strip()}")
    restore(cwd, branching.get_story_base_branch(smm_dir, cwd))
    return state


class InspectRow(NamedTuple):
    story_id: str
    wt_path: str
    tip_sha: str
    restore_ref: str


class InspectSnapshot(NamedTuple):
    rows: list[InspectRow]
    main_state: str | None


def inspect(smm_dir: Path, cwd: str) -> InspectSnapshot:
    """Read-only prepare-readiness snapshot for the /xp-accept preload.

    Touches nothing — the preload runs on every load and must be
    side-effect-free. Each ``rows`` entry is an ``InspectRow``
    (``story_id, wt_path, tip_sha, restore_ref``) for a live teammate worktree
    (the tip + base the SKILL would prepare against). ``main_state`` flags a
    window that needs healing before a detached-HEAD checkout: an interrupted
    state (``detect_interrupted``) takes precedence over a merely ``"dirty"``
    tree, since the SKILL needs the specific recover signal. None when the tree
    is clean on a normal branch.

    The base ref is identical for every row, so it is read once rather than
    per-row — this runs on every /xp-accept load.
    """
    worktrees = worktree.list_live_teammate_worktree_paths(cwd)
    rows: list[InspectRow] = []
    if worktrees:
        restore_ref = branching.get_story_base_branch(smm_dir, cwd)
        rows = [
            InspectRow(
                story_id, wt_path, _tip_of_worktree(story_id, wt_path), restore_ref
            )
            for story_id, wt_path in worktrees
        ]
    main_state = detect_interrupted(cwd)
    if main_state is None and not branching.is_worktree_clean(cwd):
        main_state = "dirty"
    return InspectSnapshot(rows=rows, main_state=main_state)
