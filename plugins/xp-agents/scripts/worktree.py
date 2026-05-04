#!/usr/bin/env python3
"""Git worktree and path management utilities.

Provides worktree path resolution, creation/removal, teammate report paths,
and project-relative path normalization. All operations share a cached
git root resolution to avoid redundant subprocess calls.
"""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smm"))

import sprint_store

_WORKTREE_PREFIX = "worktree-"

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
    except (subprocess.CalledProcessError, FileNotFoundError, NotADirectoryError):
        root = None
    _git_root_cache[cwd] = root
    return root


def _clear_git_root_cache() -> None:
    """Clear the git root cache. For testing only."""
    _git_root_cache.clear()


def worktree_path(name: str, cwd: str) -> Path:
    """Return the path to a worktree: {git_root}/.claude/worktrees/{name}."""
    root = resolve_git_root(cwd)
    if not root:
        raise RuntimeError(f"Not a git repository: {cwd}")
    return Path(root) / ".claude" / "worktrees" / name


def remove_worktree(name: str, cwd: str, force_branch: bool = False) -> None:
    """Remove a git worktree directory, branch, and prune stale entries."""
    try:
        wt = worktree_path(name, cwd)
    except RuntimeError:
        return
    if wt.is_dir():
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt)],
            cwd=cwd,
            capture_output=True,
        )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=cwd,
        capture_output=True,
    )
    flag = "-D" if force_branch else "-d"
    subprocess.run(
        ["git", "branch", flag, name],
        cwd=cwd,
        capture_output=True,
    )


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
    wt_marker = f"/.claude/worktrees/{_WORKTREE_PREFIX}story-"
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


def find_closing_teammate_worktree(smm_dir: Path, cwd: str) -> tuple[str, str] | None:
    """Locate the teammate worktree corresponding to the just-done story.

    Returns ``(abs_path, branch)`` for the live teammate worktree whose
    sprint.json story has ``status == "done"`` — implicit-derivation
    discovery used by /xp-story-close to know which teammate worktree
    it's closing without requiring /xp-accept to pass context. Returns
    ``None`` when no live teammate worktree matches a done story (solo
    flow, or no teammates running).

    Per /xp-accept's per-story dispatch loop (Step 1.0→2→2b runs per
    story before moving to the next), at most ONE done-status story
    can have a live worktree at /xp-story-close dispatch time. Two or
    more matches signals a broken iteration model — raise ValueError
    rather than guess which to close.
    """
    sprint = sprint_store.load_sprint(smm_dir)
    if sprint is None:
        return None
    stories_by_id = {s["id"]: s for s in sprint.get("stories", [])}
    skip = len(_WORKTREE_PREFIX)
    matches: list[tuple[str, str]] = []
    for wt_path, branch in _iter_live_teammate_worktrees(cwd):
        story_id = Path(wt_path).name[skip:]
        story = stories_by_id.get(story_id)
        if story is None or story.get("status") != "done":
            continue
        matches.append((wt_path, branch))
    if len(matches) > 1:
        ids = sorted(Path(p).name[skip:] for p, _ in matches)
        raise ValueError(
            "multiple done stories with live teammate worktrees "
            f"({', '.join(ids)}); /xp-accept iteration is expected to "
            "dispatch /xp-story-close per story, not in batch"
        )
    return matches[0] if matches else None


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
    return smm_dir / f".teammate-report-{name}.txt"


def story_assignment_path(smm_dir: Path, name: str) -> Path:
    """Return the path to a teammate's story assignment file."""
    return smm_dir / f".story-assignment-{name}"


def write_story_assignment(smm_dir: Path, name: str, story_id: str) -> None:
    """Atomically write story assignment marker with symlink rejection."""
    from _append_impl import write_text_atomic

    path = story_assignment_path(smm_dir, name)
    if path.is_symlink():
        raise OSError(f"Refusing to write to symlink: {path}")
    write_text_atomic(path, story_id)


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
