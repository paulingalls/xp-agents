#!/usr/bin/env python3
"""Shared git-hook detection primitives.

Two consumers compose these differently:
- ``seed_detect.has_git_hooks`` (intent-aware) — ``has_framework_marker`` OR
  ``will_fire_hook`` OR a content-sniff fallback for non-executable scripts
  that gesture at hooks. Used by SMM seeding to decide whether the project is
  hook-aware, where a declared-but-uninstalled runner still counts.
- ``close_review_support.pre_commit_hook_present`` (strict) — ``will_fire_hook``
  alone. Used by close-skill preloads to decide whether to nudge "run the
  project's test command before merging" prose, where only a hook git will
  really run counts.

The semantic divergence is encoded at composition time, not via duplicated
checks: the marker leg is the one that separates the two questions, so only the
intent-aware consumer composes it.
"""

import os
import subprocess
from pathlib import Path

_FRAMEWORK_MARKERS = (
    "lefthook.yml",
    ".lefthook.yml",
    ".husky/pre-commit",
    ".pre-commit-config.yaml",
)

_HOOK_NAMES = ("pre-commit", "pre-push")


def has_framework_marker(repo_root: str) -> bool:
    """Project declares hooks via a runner config (lefthook, husky, pre-commit)."""
    root = Path(repo_root)
    return any((root / marker).exists() for marker in _FRAMEWORK_MARKERS)


def resolved_hooks_dir(repo_root: str) -> Path:
    """Return the hooks dir git uses (``core.hooksPath`` override or ``.git/hooks``).

    Asks git rather than joining ``.git/hooks`` and reading ``core.hooksPath``
    separately: in a linked worktree ``.git`` is a FILE pointing at the shared
    common dir, so the join names a path that never exists there even when the
    hooks are installed and will fire. ``rev-parse --git-path hooks`` answers
    the worktree and the override in one call, with tilde already expanded.
    Relative results still resolve against the repo root, and a failed call
    falls back to the plain join without raising.

    Guarded on ``<root>/.git`` existing first, because ``rev-parse`` answers
    about the repo it FINDS by walking up from cwd. Asked about a plain
    directory nested under a repo it reports the ANCESTOR's hooks dir and
    exits 0 — so an unguarded call describes a different repository than the
    one it was handed, and both consumers then speak about that other repo.
    The guard is an existence check, not an ``is_dir``: a linked worktree's
    ``.git`` is a file, and that is the case this function exists for.
    """
    if not (Path(repo_root) / ".git").exists():
        return Path(repo_root) / ".git" / "hooks"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-path", "hooks"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        hooks_path = result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        hooks_path = ""
    if not hooks_path:
        return Path(repo_root) / ".git" / "hooks"
    path = Path(hooks_path).expanduser()
    return path if path.is_absolute() else Path(repo_root) / path


def has_executable_hook(repo_root: str) -> bool:
    """An executable ``pre-commit`` or ``pre-push`` exists in the resolved hooks dir."""
    hooks_dir = resolved_hooks_dir(repo_root)
    return any(os.access(hooks_dir / name, os.X_OK) for name in _HOOK_NAMES)


def will_fire_hook(repo_root: str) -> bool:
    """Strict: will git actually fire a hook on commit/push?

    An executable hook in the resolved hooks dir is the whole of it —
    ``has_executable_hook`` already resolves the dir the way git does, so
    there is nothing else git consults.

    A framework marker is deliberately NOT part of this. ``lefthook.yml`` on
    disk declares that a runner WOULD install a hook; until someone runs the
    installer, git fires nothing, and answering "present" for such a clone
    suppresses the close preloads' "the merge fires no project tests"
    guidance. The declared-intent question lives at the consumer that wants
    it — ``seed_detect.has_git_hooks`` composes the marker leg itself.
    """
    return has_executable_hook(repo_root)
