#!/usr/bin/env python3
"""Agent identity resolution utilities.

Resolves agent identity from hook input, worktree CWD path, or defaults.
Detects CLI teammates by worktree directory prefix.
"""

import os
import re
import subprocess
from pathlib import Path

# Single source of truth for the LEGACY in-repo worktree directory under each
# project root. Consumed by hooks (pre_tool_bash matcher), worktree path
# resolution (worktree.py re-exports it for the out-of-repo fallback), and test
# fixtures (capstone E2E). Trailing slash disambiguates `.claude/worktrees/`
# from any future sibling that starts the same way. Lives in identity.py (not
# worktree.py) because worktree.py imports identity — putting it in identity
# avoids a circular dependency.
WORKTREE_PATH_FRAGMENT = ".claude/worktrees/"
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
    """Extract the teammate worktree dir name from cwd, or None if not one.

    Keys on the location-independent `worktree-story-` SEGMENT rather than a
    `.claude/worktrees/` parent fragment, so detection keeps firing after
    worktrees move out of the repo to `{project-id}/worktrees/` (story-024) —
    the load-bearing teammate-detection contract. A path segment must START
    with the prefix, so the plural parent `worktrees` (no dash) never
    false-positives.

    Tolerates a missing/None cwd (hook payloads may carry an explicit
    `"cwd": null`); returns None rather than raising on falsy input. Non-teammate
    worktrees (e.g. `explore-abc`) now return None — every real consumer gates on
    `is_teammate_agent_id` afterward, so this is more correct, not a regression.
    """
    if not cwd:
        return None
    for seg in cwd.split("/"):
        if seg.startswith(_TEAMMATE_PREFIX):
            return seg
    return None


def _process_cwd() -> str:
    """The process working directory, or "" if it is unavailable.

    ``os.getcwd()`` raises ``FileNotFoundError`` when the cwd has been deleted
    out from under the process. is_worktree_teammate runs inside every hook, so
    it must degrade to "" rather than crash the hook on that rare edge.
    """
    try:
        return os.getcwd()
    except OSError:
        return ""


def teammate_name_from_env() -> str | None:
    """The teammate name spawn_teammate.py exported, or None.

    An in-place (solo-delegation) teammate runs in the MAIN checkout, so its
    cwd carries no worktree path marker for `extract_worktree_name` to key on —
    but spawn_teammate still exports ``XP_TEAMMATE_NAME``. Commit attribution
    uses this to recover the name-keyed assignment when the cwd marker is absent.
    """
    name = os.environ.get(_XP_TEAMMATE_ENV, "").strip()
    return name or None


def is_teammate_agent_id(agent_id: str) -> bool:
    """True if `agent_id` belongs to a CLI teammate (e.g., 'worktree-story-001')."""
    return agent_id.startswith(_TEAMMATE_PREFIX)


def in_place_teammate_name(smm_dir: Path | None = None) -> str | None:
    """The live in-place teammate's name, or None.

    Shared env leg behind `is_worktree_teammate`, `tdd_check._reader_scope`,
    and `pre_tool_skill._is_live_teammate` — the three sites that used to roll
    this guard by hand. `XP_TEAMMATE_NAME` is a documented leaky var, so it is
    trusted only when spawn_teammate's lifetime-scoped in-place marker is live
    for that name under the resolved SMM dir.

    *smm_dir* locates the marker; when None it resolves through the same
    validated resolver every hook shares (`_common.get_validated_smm_dir` —
    the `SMM_DIR` env, else derived via `init.sh`). When that resolver cannot
    produce a directory, the marker is unverifiable and this fails closed
    (None) — it never hands None to `in_place_teammate_from_env`.
    """
    env_name = teammate_name_from_env()
    if env_name is None or not is_teammate_agent_id(env_name):
        return None
    # Deferred import: identity carries no sys.path shim of its own (its
    # module-level imports are stdlib-only) — a top-level `import _common`
    # would resolve only by the side effect of some other module having
    # already inserted smm/ onto sys.path. _common.py:13 does that insert
    # itself, and every caller of this function already imports identity
    # after running that shim.
    import _common

    resolved_smm_dir = _common.get_validated_smm_dir(smm_dir)
    if resolved_smm_dir is None:
        return None
    # Deferred import: worktree imports identity at module load, so a
    # top-level import here would cycle (mirrors is_worktree_teammate below).
    import worktree

    if worktree.in_place_teammate_from_env(resolved_smm_dir, env_name):
        return env_name
    return None


def is_worktree_teammate(input_data: dict, smm_dir: Path | None = None) -> bool:
    """Detect CLI teammates by worktree cwd path, or by XP_TEAMMATE_NAME env
    var guarded on a live in-place marker.

    The cwd leg catches worktree teammates directly. It reads the hook
    payload's ``cwd`` first, then falls back to the process cwd
    (``os.getcwd()``): a worktree teammate's hook process runs INSIDE the
    worktree, so its process cwd carries the worktree marker even when the
    payload omits ``cwd`` or carries an explicit ``"cwd": null``. Without this
    fallback such a teammate would slip past the cwd leg and — because worktree
    spawns never write the in-place marker — also past the marker-guarded env
    leg, misidentifying it as the lead.

    The env leg exists for in-place (solo-delegation) teammates whose cwd is
    the main checkout — but ``XP_TEAMMATE_NAME`` is a documented leaky var, so a
    lead that inherited it must NOT be misidentified. A lead's own process cwd
    is the main checkout (no worktree marker), so the cwd fallback never
    misfires for it. Trust the env only when spawn_teammate's lifetime-scoped
    in-place marker is live for that name; a leaked env with no marker is not a
    teammate. Delegates to ``in_place_teammate_name`` — the shared helper that
    also backs ``tdd_check._reader_scope`` and
    ``pre_tool_skill._is_live_teammate`` — so every caller (session_start,
    kickoff/stop gates, pre_tool_write, session_end, bash_post_tool) inherits
    the same guard.

    *smm_dir* locates the marker; when None it resolves through the same
    validated resolver every hook shares (``_common.get_validated_smm_dir`` —
    the ``SMM_DIR`` env, else derived via ``init.sh``). With neither a param
    nor a resolvable dir, the marker is unverifiable and the env leg fails
    closed (not a teammate).
    """
    name = extract_worktree_name(input_data.get("cwd", "")) or extract_worktree_name(
        _process_cwd()
    )
    if name and name.startswith(_TEAMMATE_PREFIX):
        return True
    return in_place_teammate_name(smm_dir) is not None


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
