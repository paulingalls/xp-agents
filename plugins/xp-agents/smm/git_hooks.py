#!/usr/bin/env python3
"""Shared git-hook detection primitives.

Two consumers compose these differently:
- ``seed_detect.has_git_hooks`` (intent-aware) — ``will_fire_hook`` plus a
  content-sniff fallback for non-executable scripts that gesture at hooks.
  Used by SMM seeding to decide whether the project is hook-aware.
- ``close_review_support.pre_commit_hook_present`` (strict) — ``will_fire_hook``
  alone. Used by close-skill preloads to decide whether to nudge "run the
  project's test command before merging" prose.

The semantic divergence (content-sniff vs exec-bit) is encoded at
composition time, not via duplicated marker checks.
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

    Honors tilde expansion and resolves relative paths against the repo root,
    matching git's own semantics.
    """
    try:
        result = subprocess.run(
            ["git", "config", "core.hooksPath"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        override = result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        override = ""
    if not override:
        return Path(repo_root) / ".git" / "hooks"
    path = Path(override).expanduser()
    return path if path.is_absolute() else Path(repo_root) / path


def has_executable_hook(repo_root: str) -> bool:
    """An executable ``pre-commit`` or ``pre-push`` exists in the resolved hooks dir."""
    hooks_dir = resolved_hooks_dir(repo_root)
    return any(os.access(hooks_dir / name, os.X_OK) for name in _HOOK_NAMES)


def will_fire_hook(repo_root: str) -> bool:
    """Strict: will git actually fire a hook on commit/push?

    Composition: a framework marker declares intent runners will honor, OR
    an executable hook is wired up directly.
    """
    return has_framework_marker(repo_root) or has_executable_hook(repo_root)
