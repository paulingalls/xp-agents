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
    """Yield worktree paths under `.claude/worktrees/worktree-story-*`
    that are non-prunable and exist on disk.

    Shared by has_live_teammates (boolean check) and
    find_teammate_worktree_for_story (per-story lookup).
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
    wt_marker = "/.claude/worktrees/worktree-story-"
    for block in out.split("\n\n"):
        if "prunable" in block:
            continue
        for line in block.splitlines():
            if line.startswith("worktree ") and wt_marker in line:
                wt_path = line[len("worktree ") :]
                if Path(wt_path).is_dir():
                    yield wt_path


def has_live_teammates(cwd: str) -> bool:
    """Return True if any non-prunable `worktree-story-*` worktree is registered.

    Uses `git worktree list --porcelain` so the check reflects real git
    state (not filesystem artifacts). Skips prunable entries — those are
    stale registrations whose directories no longer exist. Falls back to
    False when cwd is outside a git repo or the command fails.
    """
    return any(_iter_live_teammate_worktrees(cwd))


def list_live_teammate_worktree_names(cwd: str) -> list[str]:
    """Return the basename of every live `worktree-story-*` worktree.

    Powers /xp-accept's preload (replaces an inline porcelain parser).
    Same data source as has_live_teammates / find_teammate_worktree_for_story
    so all three queries stay consistent if porcelain shape changes.
    """
    return [Path(wt_path).name for wt_path in _iter_live_teammate_worktrees(cwd)]


def find_teammate_worktree_for_story(story_id: str, cwd: str) -> str | None:
    """Return the worktree NAME (e.g. `worktree-story-042`) for a teammate
    that's working on `story_id`, or None if no live worktree matches.

    Powers /xp-story-close's Step 7b cleanup gate: solo mode has no
    matching worktree (returns None, cleanup skipped); teammate mode
    returns the exact name to pass as `cleanup_teammate.py --name`.
    Filters for exact `worktree-<story_id>` directory names — the
    naming convention defined in spawn_teammate.py + identity._TEAMMATE_PREFIX.
    """
    target = f"worktree-{story_id}"
    for wt_path in _iter_live_teammate_worktrees(cwd):
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
