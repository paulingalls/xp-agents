#!/usr/bin/env python3
"""Shared helpers for all hook scripts.

DRY module providing SMM resolution, hook I/O, recursion prevention,
event reading, and watermark management.
"""

import contextlib
import functools
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

# Make smm/ importable so we can use _append_impl as the foundational module
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import (
    PRIORITY_ASSUMED,  # noqa: F401
    PRIORITY_BLOCKING,  # noqa: F401
    PRIORITY_INFO,  # noqa: F401
    _validate_agent_id,  # noqa: F401
    parse_jsonl,
    write_watermark,  # noqa: F401
)
from _append_impl import _validate_smm_dir as validate_smm_dir
from _append_impl import (
    write_json_atomic as _write_json_atomic,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BlockedError(Exception):
    """Raised when a tool call should be blocked (exit 2 with stderr message).

    Optional system_message provides user-facing context for the block.
    """

    def __init__(self, message: str, system_message: str | None = None) -> None:
        super().__init__(message)
        self.system_message = system_message


# ---------------------------------------------------------------------------
# Event type and priority constants
# ---------------------------------------------------------------------------

# Event types — mirrors smm/schema.json enum
COMMIT = "commit"
CUSTOMER_INPUT = "customer_input"
CUSTOMER_INTENT = "customer_intent"
DEBT = "debt"
GOAL = "goal"
STATUS = "status"
DECISION = "decision"
CONVENTION = "convention"
CONCERN = "concern"
DISCOVERY = "discovery"
QUESTION = "question"
ANSWER = "answer"
ASSUMPTION = "assumption"
SESSION_END = "session_end"
RETROSPECTIVE = "retrospective"


def subagent_started_content(agent_id: str) -> str:
    """Canonical content string for subagent start events."""
    return f"Subagent {agent_id} started"


def subagent_completed_content(agent_id: str) -> str:
    """Canonical content string for subagent completion events."""
    return f"Subagent {agent_id} completed"


# Question priorities imported from _append_impl at module level


# ---------------------------------------------------------------------------
# SMM path resolution
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def resolve_smm_dir() -> Path | None:
    """Derive the SMM directory from git-common-dir.

    Uses CLAUDE_PLUGIN_DATA as base (standard plugin ecosystem path),
    falls back to ~/.claude/xp-agents for --plugin-dir development mode.
    Returns None if not in a git repo (graceful degradation for hooks).
    Cached — git-common-dir is deterministic for a given working directory.
    """
    try:
        git_common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    git_common_path = Path(git_common)
    if not git_common_path.is_absolute():
        git_common_path = git_common_path.resolve()

    project_id = hashlib.sha256(str(git_common_path).encode()).hexdigest()[:12]
    base_dir = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base_dir:
        return Path(base_dir) / project_id / "smm"
    return Path.home() / ".claude" / "xp-agents" / project_id / "smm"


# ---------------------------------------------------------------------------
# Hook I/O
# ---------------------------------------------------------------------------


_MAX_STDIN_SIZE = 1_048_576  # 1 MB


def read_hook_input() -> dict:
    """Read JSON from stdin with size limit. On error: exit 0 (graceful)."""
    try:
        raw = sys.stdin.read(_MAX_STDIN_SIZE + 1)
        if len(raw) > _MAX_STDIN_SIZE:
            sys.exit(0)
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)


def hook_output(
    event_name: str, context: str, system_message: str | None = None
) -> None:
    """Print hookSpecificOutput JSON to stdout.

    If system_message is provided, it is shown to the user as a notification
    (separate from additionalContext which only the agent sees).
    """
    output: dict = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    }
    if system_message:
        output["systemMessage"] = system_message
    print(json.dumps(output, ensure_ascii=False))


def block_output(reason: str, system_message: str) -> None:
    """Print block decision JSON with systemMessage to stdout."""
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": reason,
                "systemMessage": system_message,
            }
        )
    )


# ---------------------------------------------------------------------------
# Recursion prevention
# ---------------------------------------------------------------------------


def is_xp_agent(input_data: dict) -> bool:
    """Check if this is one of our own agent hooks (xp- prefix)."""
    agent_type = input_data.get("agent_type", "")
    return isinstance(agent_type, str) and agent_type.startswith("xp-")


def is_task_notification(prompt: str) -> bool:
    """Check if a prompt is a background agent task-notification, not user input."""
    return isinstance(prompt, str) and prompt.strip().startswith("<task-notification>")


# ---------------------------------------------------------------------------
# Plugin root resolution
# ---------------------------------------------------------------------------


def resolve_plugin_root() -> Path:
    """Resolve plugin root from CLAUDE_PLUGIN_ROOT env var or __file__."""
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).parent.parent


@functools.lru_cache(maxsize=1)
def load_xp_values() -> str:
    """Load XP_VALUES.md from plugin root."""
    try:
        path = resolve_plugin_root() / "XP_VALUES.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        pass
    return ""


@functools.lru_cache(maxsize=1)
def load_process_guide() -> str:
    """Load PROCESS_GUIDE.md from plugin root."""
    try:
        path = resolve_plugin_root() / "PROCESS_GUIDE.md"
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        pass
    return ""


@functools.lru_cache(maxsize=1)
def load_teammate_guide() -> str:
    """Load TEAMMATE_GUIDE.md from plugin root."""
    try:
        guide_path = resolve_plugin_root() / "TEAMMATE_GUIDE.md"
        if guide_path.is_file():
            return guide_path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Event reading (no locking — for hook scripts that don't need atomicity)
# ---------------------------------------------------------------------------


_MAX_EVENTS_FILE_SIZE = 10_485_760  # 10 MB


def read_events_raw(smm_dir: Path) -> list[dict]:
    """Parse events.jsonl, skip malformed lines, no locking."""
    events_file = smm_dir / "events.jsonl"
    try:
        if events_file.stat().st_size > _MAX_EVENTS_FILE_SIZE:
            return []
        raw = events_file.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []

    events, _ = parse_jsonl(raw)
    return events


# ---------------------------------------------------------------------------
# SMM directory validation (imported from _append_impl, with convenience wrapper)
# ---------------------------------------------------------------------------


def try_validate_smm_dir(smm_dir: Path | None) -> Path | None:
    """Validate SMM dir, returning None on failure instead of raising."""
    if smm_dir is None:
        return None
    try:
        validate_smm_dir(smm_dir)
        return smm_dir
    except ValueError:
        return None


def get_validated_smm_dir(smm_dir: Path | None = None) -> Path | None:
    """Resolve and validate SMM directory in one call.

    Combines resolve_smm_dir() + try_validate_smm_dir() to replace
    the 3-line boilerplate pattern used in 24+ hook scripts.
    """
    if smm_dir is None:
        smm_dir = resolve_smm_dir()
    return try_validate_smm_dir(smm_dir)


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
    # Use realpath only if the path exists (avoids platform-specific
    # resolution of fictional paths like /home on macOS → /System/Volumes/Data/home)
    absolute = resolved if os.path.exists(resolved) else os.path.normpath(full)

    # Strip git root to get project-relative path
    git_root = resolve_git_root(cwd)
    if git_root:
        prefix = os.path.realpath(git_root).rstrip("/") + "/"
        if absolute.startswith(prefix):
            return absolute[len(prefix) :]
        # normpath may not resolve symlinks consistently with realpath(git_root)
        # (e.g., /var vs /private/var on macOS). For non-existent files, walk up
        # to the nearest existing ancestor, resolve its symlinks, and retry.
        # This fixes cross-worktree coordination where Agent A's files don't
        # exist in Agent B's worktree.
        if not os.path.exists(full):
            cur = full
            tail_parts: list[str] = []
            while cur and not os.path.exists(cur):
                cur, tail = os.path.split(cur)
                if not tail:  # reached root ("/", "") — stop
                    break
                tail_parts.append(tail)
            if cur and os.path.exists(cur):
                resolved_ancestor = os.path.realpath(cur)
                for part in reversed(tail_parts):
                    resolved_ancestor = os.path.join(resolved_ancestor, part)
                if resolved_ancestor.startswith(prefix):
                    return resolved_ancestor[len(prefix) :]
    return absolute


def extract_file_path(tool_name: str, tool_input: dict) -> str | None:
    """Extract file_path from tool_input for write tools."""
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return tool_input.get("file_path")
    return None


def make_event(event_type: str, agent_id: str, content: str, **extra) -> dict:
    """Build a minimal SMM event dict with standard fields."""
    import uuid
    from datetime import datetime, timezone

    event = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "agent_id": agent_id,
        "content": content,
        "schema_version": 1,
    }
    event.update(extra)
    return event


def count_unresolved_concerns(events: list[dict]) -> int:
    """Count concern events that have no resolution."""
    from resolution import compute_resolutions

    concern_ids = {e["id"] for e in events if e.get("type") == CONCERN and e.get("id")}
    if not concern_ids:
        return 0
    resolved = compute_resolutions(events)["resolved_concern_ids"]
    return len(concern_ids - resolved)


def has_final_status(events: list[dict], agent_id: str = "main") -> bool:
    """Check if the last event from the given agent is a status event."""
    for e in reversed(events):
        if e.get("agent_id") == agent_id:
            return e.get("type") == STATUS
    return True  # No events from this agent → nothing to warn about


def write_json_atomic(file_path: Path, data: dict) -> None:
    """Atomic JSON write: tempfile + chmod 600 + rename.

    Caller must ensure file_path.parent is a validated SMM directory.
    Rejects symlink targets to prevent symlink-based overwrites.
    """
    if file_path.is_symlink():
        raise ValueError(f"Refusing to write to symlink: {file_path}")
    _write_json_atomic(file_path, data)


def append_safe(smm_dir: Path, event: dict) -> None:
    """Validate and append event, swallowing lock errors."""
    import _append_impl

    errors = _append_impl.validate_event(event)
    if not errors:
        with contextlib.suppress(_append_impl.LockTimeoutError):
            _append_impl.append_event(smm_dir, event)


def bulk_append_safe(smm_dir: Path, events: list[dict]) -> None:
    """Filter invalid events, then bulk-append valid ones atomically."""
    import _append_impl

    valid = [e for e in events if not _append_impl.validate_event(e)]
    if valid:
        with contextlib.suppress(_append_impl.LockTimeoutError, ValueError):
            _append_impl.bulk_append(smm_dir, valid)


# Coordination: see coordination.py
# Concerns/conflicts: see concerns.py


# ---------------------------------------------------------------------------
# SMM content wrapping (security: structural delimiters for additionalContext)
# ---------------------------------------------------------------------------


def wrap_smm_context(content: str) -> str:
    """Wrap SMM content in XML tags for safe injection."""
    return f"<smm-context>\n{content}</smm-context>"


# Security review: see security.py


# Debt lookup: see concerns.py


# write_watermark imported from _append_impl at module level
