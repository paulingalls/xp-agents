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
checks. That was always the stated design here, but ``will_fire_hook`` used to
fold the marker in itself — so both consumers received the intent-aware answer
and the strict one had no way to ask its own question.
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

    An executable hook in the resolved hooks dir is the whole of it —
    ``has_executable_hook`` already honors ``core.hooksPath``, so there is
    nothing else git consults.

    A framework marker is deliberately NOT part of this. ``lefthook.yml`` on
    disk declares that a runner WOULD install a hook; until someone runs the
    installer, git fires nothing. Folding the marker in here made this
    function answer a declared-intent question while its name and docstring
    promised a will-it-fire one, and the two are not the same in the case
    that matters: a clone that has the config and has never run ``make
    setup``. That reported the commit gate present in this repo's own tree
    while ``.git/hooks/pre-commit`` did not exist, which suppressed the close
    preloads' "the merge fires no project tests" guidance.

    The declared-intent question did not disappear — it moved to the consumer
    that wants it. ``seed_detect.has_git_hooks`` composes the marker leg
    itself, which is what this module's docstring already said happens.
    """
    return has_executable_hook(repo_root)
