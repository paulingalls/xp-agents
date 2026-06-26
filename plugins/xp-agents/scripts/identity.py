#!/usr/bin/env python3
"""Agent identity resolution utilities.

Resolves agent identity from hook input, worktree CWD path, or defaults.
Detects CLI teammates by worktree directory prefix.
"""

import os
import re
import subprocess

# Single source of truth for the worktree directory under each project root.
# Consumed by hooks (pre_tool_bash matcher), worktree path resolution
# (worktree.py re-exports this), test fixtures (capstone E2E), and the
# private path-marker derived below. Trailing slash disambiguates
# `.claude/worktrees/` from any future sibling that starts the same way.
# Lives in identity.py (not worktree.py) because worktree.py imports
# identity — putting it in identity avoids a circular dependency.
WORKTREE_PATH_FRAGMENT = ".claude/worktrees/"
_WORKTREE_PATH_MARKER = f"/{WORKTREE_PATH_FRAGMENT}"
_TEAMMATE_PREFIX = "worktree-story-"
_XP_TEAMMATE_ENV = "XP_TEAMMATE_NAME"

# Matches `<user>/story-NNN[-<slug>]` and captures the `story-NNN` group.
# Story ids are zero-padded by sprint-start convention but the regex
# accepts any digit count for resilience. Slug suffix is optional —
# spawn_teammate's worktree names omit it.
_STORY_BRANCH_RE = re.compile(r"^[^/]+/(story-\d+)(?:-.*)?$")


def _git_stdout(args: list[str], cwd: str) -> str:
    """Run a git command and return stripped stdout, or empty on failure."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.SubprocessError, OSError):
        return ""


def get_current_branch(cwd: str) -> str:
    """Get current git branch name, or empty string on failure."""
    return _git_stdout(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)


def extract_story_id(branch_name: str) -> str | None:
    """Extract `story-NNN` from a `<user>/story-NNN-<slug>` branch name.

    Returns None for branches that don't match the convention (free
    branches, plan branches, primary, story-prefixed branches without
    a user namespace). Powers /xp-story-close's teammate-worktree
    cleanup lookup so it can find the matching `worktree-story-NNN`.
    """
    if not branch_name:
        return None
    m = _STORY_BRANCH_RE.match(branch_name)
    return m.group(1) if m else None


def extract_worktree_name(cwd: str | None) -> str | None:
    """Extract worktree directory name from cwd, or None if not in worktree.

    Tolerates a missing/None cwd (hook payloads may carry an explicit
    `"cwd": null`); returns None rather than raising on falsy input.
    """
    if not cwd:
        return None
    idx = cwd.find(_WORKTREE_PATH_MARKER)
    if idx < 0:
        return None
    tail = cwd[idx + len(_WORKTREE_PATH_MARKER) :]
    return tail.split("/")[0]


def is_teammate_agent_id(agent_id: str) -> bool:
    """True if `agent_id` belongs to a CLI teammate (e.g., 'worktree-story-001')."""
    return agent_id.startswith(_TEAMMATE_PREFIX)


def is_worktree_teammate(input_data: dict) -> bool:
    """Detect CLI teammates by worktree cwd path or XP_TEAMMATE_NAME env var."""
    name = extract_worktree_name(input_data.get("cwd", ""))
    if name and name.startswith(_TEAMMATE_PREFIX):
        return True
    env_name = os.environ.get(_XP_TEAMMATE_ENV, "")
    return env_name.startswith(_TEAMMATE_PREFIX)


def resolve_agent_id(input_data: dict) -> str:
    """Resolve agent_id from hook input, worktree path, or default."""
    agent_id = input_data.get("agent_id", "")
    if agent_id:
        return agent_id
    return resolve_agent_id_from_cwd(input_data.get("cwd", ""))


def resolve_agent_id_from_cwd(cwd: str) -> str:
    """Resolve agent_id from a cwd path — worktree name or 'main' fallback.

    For skill-invoked scripts that have cwd but no hook input_data.
    """
    return extract_worktree_name(cwd) or "main"


def _slugify(s: str) -> str:
    """Lowercase, replace non-alphanumeric with dash, collapse, strip."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _git_config(key: str, cwd: str) -> str:
    """Read a git config value, or return empty string on failure."""
    return _git_stdout(["git", "config", key], cwd)


def user_namespace(cwd: str) -> str:
    """Derive a branch-naming namespace from git config.

    Tries user.email local-part first, falls back to user.name, then "user".
    """
    email = _git_config("user.email", cwd)
    if email and "@" in email:
        slug = _slugify(email.split("@")[0])
        if slug:
            return slug

    name = _git_config("user.name", cwd)
    if name:
        slug = _slugify(name)
        if slug:
            return slug

    return "user"
