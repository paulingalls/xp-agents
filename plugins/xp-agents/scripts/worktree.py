#!/usr/bin/env python3
"""Git worktree and path management utilities.

Provides worktree path resolution, creation/removal, teammate report paths,
and project-relative path normalization. All operations share a cached
git root resolution to avoid redundant subprocess calls.
"""

import os
import subprocess
from pathlib import Path

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
    """Remove a git worktree directory and its branch."""
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
    flag = "-D" if force_branch else "-d"
    subprocess.run(
        ["git", "branch", flag, name],
        cwd=cwd,
        capture_output=True,
    )


def teammate_report_path(smm_dir: Path, name: str) -> Path:
    """Return the path to a teammate's report file."""
    return smm_dir / f".teammate-report-{name}.txt"


def story_assignment_path(smm_dir: Path, name: str) -> Path:
    """Return the path to a teammate's story assignment file."""
    return smm_dir / f".story-assignment-{name}"


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
