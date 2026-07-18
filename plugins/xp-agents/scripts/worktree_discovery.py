#!/usr/bin/env python3
"""Teammate-worktree discovery and query helpers.

Extracted from worktree.py to keep modules focused on a single
responsibility (worktree.py crossed the 500-line ceiling). worktree.py
re-exports every name here by identity, so `worktree.X IS
worktree_discovery.X` for callers and `mock.patch("...worktree.X")` sites.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import identity
import sprint_status
import sprint_store

_WORKTREE_PREFIX = "worktree-"


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
    # Location-independent: `/worktree-story-` matches both the new out-of-repo
    # placement and the legacy in-repo one (migration-safe), without a
    # `.claude/worktrees/` parent (story-024). Single-source the teammate
    # segment from identity so a naming rename can't drift the two apart.
    wt_marker = f"/{identity._TEAMMATE_PREFIX}"
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
