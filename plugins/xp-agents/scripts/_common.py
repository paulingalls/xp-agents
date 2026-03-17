#!/usr/bin/env python3
"""Shared helpers for all hook scripts.

DRY module providing SMM resolution, hook I/O, recursion prevention,
event reading, and watermark management.
"""

import bisect
import contextlib
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Make smm/ importable so we can use _append_impl as the foundational module
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import (
    PRIORITY_ASSUMED,  # noqa: F401
    PRIORITY_BLOCKING,
    PRIORITY_INFO,  # noqa: F401
    _validate_agent_id,  # noqa: F401
    write_watermark,  # noqa: F401
)
from _append_impl import _validate_smm_dir as validate_smm_dir

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BlockedError(Exception):
    """Raised when a tool call should be blocked (exit 2 with stderr message)."""


# ---------------------------------------------------------------------------
# Event type and priority constants
# ---------------------------------------------------------------------------

# Event types — mirrors smm/schema.json enum
CUSTOMER_INPUT = "customer_input"
SECURITY_REVIEW_REQUESTED = "security_review_requested"
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
PAIR_GUIDANCE = "pair_guidance"
SESSION_END = "session_end"
RETROSPECTIVE = "retrospective"

# Question priorities imported from _append_impl at module level


# ---------------------------------------------------------------------------
# SMM path resolution
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def resolve_smm_dir() -> Path | None:
    """Derive the SMM directory from git-common-dir.

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


def hook_output(event_name: str, context: str) -> None:
    """Print hookSpecificOutput JSON to stdout."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Recursion prevention
# ---------------------------------------------------------------------------


def is_xp_agent(input_data: dict) -> bool:
    """Check if this is one of our own agent hooks (xp- prefix)."""
    agent_type = input_data.get("agent_type", "")
    return isinstance(agent_type, str) and agent_type.startswith("xp-")


# ---------------------------------------------------------------------------
# Plugin root resolution
# ---------------------------------------------------------------------------


def resolve_plugin_root() -> Path:
    """Resolve plugin root from CLAUDE_PLUGIN_ROOT env var or __file__."""
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).parent.parent


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

    events: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if isinstance(event, dict):
                events.append(event)
        except json.JSONDecodeError:
            continue

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


def normalize_path(file_path: str, cwd: str) -> str:
    """Resolve a file path against cwd, return normalized string.

    Uses realpath when the path exists to resolve symlinks, preventing
    symlink-based confusion in working_on overlap detection. Falls back
    to normpath for non-existent paths (e.g., planned file writes).
    """
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(cwd) / p
    full = str(p)
    resolved = os.path.realpath(full)
    # Use realpath only if the path exists (avoids platform-specific
    # resolution of fictional paths like /home on macOS → /System/Volumes/Data/home)
    if os.path.exists(resolved):
        return resolved
    return os.path.normpath(full)


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


def write_json_atomic(file_path: Path, data: dict) -> None:
    """Atomic JSON write: tempfile + chmod 600 + rename.

    Caller must ensure file_path.parent is a validated SMM directory.
    Rejects symlink targets to prevent symlink-based overwrites.
    """
    if file_path.is_symlink():
        raise ValueError(f"Refusing to write to symlink: {file_path}")
    fd, tmp = tempfile.mkstemp(dir=file_path.parent, suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.chmod(tmp, 0o600)
        os.rename(tmp, file_path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def append_safe(smm_dir: Path, event: dict) -> None:
    """Validate and append event, swallowing lock errors."""
    import _append_impl

    errors = _append_impl.validate_event(event)
    if not errors:
        with contextlib.suppress(_append_impl.LockTimeoutError):
            _append_impl.append_event(smm_dir, event)


# ---------------------------------------------------------------------------
# Conflict detection (shared by post_tool_use.py and subagent_stop.py)
# ---------------------------------------------------------------------------


def make_concern(content: str, severity: str, agent_id: str) -> dict:
    """Build a concern event dict."""
    return make_event(CONCERN, agent_id, content, severity=severity)


def detect_conflicts(
    events: list[dict],
    agent_id: str,
    file_path: str | None = None,
    cwd: str | None = None,
) -> list[dict]:
    """Detect structural conflicts in the event log. Returns concern event dicts.

    When file_path/cwd are None, skip pattern 1 (overlapping working_on).
    Deduplicates: skips concerns whose content already exists in the event log.
    """
    # Collect existing concern content for deduplication
    existing_concerns = {
        e.get("content", "") for e in events if e.get("type") == CONCERN
    }
    concerns: list[dict] = []

    def _add_concern(content: str, severity: str) -> None:
        """Append concern only if not already in the event log."""
        if content not in existing_concerns:
            concerns.append(make_concern(content, severity, agent_id))
            existing_concerns.add(content)

    # 1. Overlapping working_on — another agent claims same file
    if file_path is not None and cwd is not None:
        normalized = normalize_path(file_path, cwd)
        agent_files: dict[str, list[str]] = {}
        for e in events:
            if e.get("type") == STATUS and e.get("working_on"):
                agent_files[e.get("agent_id", "")] = e["working_on"]

        for aid, files in agent_files.items():
            if aid == agent_id:
                continue
            norm_files = {normalize_path(f, cwd) for f in files}
            if normalized in norm_files:
                _add_concern(
                    f"Overlapping working_on: agent '{aid}' is also working on "
                    f"'{file_path}'. Coordinate to avoid conflicts.",
                    "medium",
                )

    # 2. Assumption contradicted by discovery
    assumptions: dict[str, dict] = {}
    for e in events:
        if e.get("type") == ASSUMPTION:
            assumptions[e.get("id", "")] = e
        elif e.get("type") == DISCOVERY:
            for ref in e.get("references", []):
                if ref in assumptions:
                    _add_concern(
                        f"Assumption contradicted: '{assumptions[ref]['content']}' "
                        f"contradicted by discovery '{e['content']}'.",
                        "high",
                    )

    # 3. Convention violation — decision diverges from convention on same topic
    conventions_by_topic: dict[str, list[dict]] = {}
    for e in events:
        if e.get("type") == CONVENTION:
            topic = e.get("topic", "")
            conventions_by_topic.setdefault(topic, []).append(e)

    for e in events:
        if e.get("type") == DECISION:
            topic = e.get("topic", "")
            if topic in conventions_by_topic:
                refs = set(e.get("references", []))
                conv_ids = {c["id"] for c in conventions_by_topic[topic]}
                if not refs & conv_ids:
                    _add_concern(
                        f"Convention violation: decision on '{topic}' "
                        "diverges from established convention.",
                        "medium",
                    )

    # 4. Stale question — 🔴 question with no answer after 20+ subsequent events
    import _append_impl

    question_positions: dict[str, int] = {}
    for i, e in enumerate(events):
        if e.get("type") == QUESTION and e.get("priority") == PRIORITY_BLOCKING:
            question_positions[e.get("id", "")] = i

    resolutions = _append_impl.compute_resolutions(events)
    answered_ids = resolutions["answered_question_ids"]

    total = len(events)
    for qid, pos in question_positions.items():
        if qid not in answered_ids and (total - pos - 1) >= 20:
            _add_concern(
                f"Stale question: blocking question (id {qid[:8]}) "
                f"has not been answered.",
                "medium",
            )

    # 5. Superseded decision — two decisions on same topic with no concern between
    decisions_by_topic: dict[str, list[tuple[int, dict]]] = {}
    concern_pos_list: list[int] = []
    for i, e in enumerate(events):
        if e.get("type") == DECISION:
            topic = e.get("topic", "")
            decisions_by_topic.setdefault(topic, []).append((i, e))
        elif e.get("type") == CONCERN:
            concern_pos_list.append(i)

    # concern_pos_list is already sorted (built in event order)
    for topic, decs in decisions_by_topic.items():
        if len(decs) < 2:
            continue
        for j in range(1, len(decs)):
            prev_pos = decs[j - 1][0]
            curr_pos = decs[j][0]
            # Binary search: any concern position in (prev_pos, curr_pos)?
            lo = bisect.bisect_right(concern_pos_list, prev_pos)
            has_concern_between = (
                lo < len(concern_pos_list) and concern_pos_list[lo] < curr_pos
            )
            if not has_concern_between:
                _add_concern(
                    f"Superseded decision: topic '{topic}' has multiple decisions "
                    f"without an intervening concern.",
                    "low",
                )

    return concerns


# ---------------------------------------------------------------------------
# Semantic reference enrichment (shared by post_tool_use.py and plan_review.py)
# ---------------------------------------------------------------------------


def _file_list_contains(paths: list, normalized_target: str, cwd: str) -> bool:
    """Check if any path in list matches normalized_target after normalization."""
    for f in paths:
        if isinstance(f, str):
            try:
                if normalize_path(f, cwd) == normalized_target:
                    return True
            except (ValueError, OSError):
                continue
    return False


def find_related_decisions(events: list[dict], file_path: str, cwd: str) -> list[str]:
    """Find event IDs of decisions/conventions that reference this file."""
    normalized = normalize_path(file_path, cwd)
    related: list[str] = []

    for e in events:
        if e.get("type") not in (DECISION, CONVENTION):
            continue
        # Check working_on field
        working_on = e.get("working_on", [])
        if isinstance(working_on, list) and _file_list_contains(
            working_on, normalized, cwd
        ):
            related.append(e["id"])
            continue
        # Check references field for normalized path matches
        refs = e.get("references", [])
        if isinstance(refs, list) and _file_list_contains(refs, normalized, cwd):
            related.append(e["id"])

    return related


# ---------------------------------------------------------------------------
# SMM content wrapping (security: structural delimiters for additionalContext)
# ---------------------------------------------------------------------------


def wrap_smm_context(content: str) -> str:
    """Wrap SMM content in XML tags for safe injection."""
    return f"<smm-context>\n{content}</smm-context>"


# ---------------------------------------------------------------------------
# Security review tracker
# ---------------------------------------------------------------------------

_COMMIT_HASH_RE = re.compile(r"^[0-9a-f]{7,40}$")


def get_head_hash(cwd: str = ".") -> str | None:
    """Get current HEAD commit hash. Returns None on failure."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            timeout=5,
        ).strip()
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return None


def security_tracker_path(smm_dir: Path, commit_hash: str) -> Path:
    """Build tracker path. Validates hash format (^[0-9a-f]{7,40}$)."""
    if not _COMMIT_HASH_RE.match(commit_hash):
        raise ValueError(f"Invalid commit hash: {commit_hash!r}")
    return smm_dir / f".security-reviewed-{commit_hash}"


def security_tracker_exists(smm_dir: Path, commit_hash: str) -> bool:
    """Check if tracker exists and is not a symlink."""
    try:
        path = security_tracker_path(smm_dir, commit_hash)
    except ValueError:
        return False
    return path.exists() and not path.is_symlink()


def write_security_tracker(smm_dir: Path, commit_hash: str) -> None:
    """Atomic write + cleanup old trackers."""
    from datetime import datetime, timezone

    path = security_tracker_path(smm_dir, commit_hash)
    data = {
        "commit_hash": commit_hash,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(path, data)
    _cleanup_old_security_trackers(smm_dir, commit_hash)


def _cleanup_old_security_trackers(smm_dir: Path, keep_hash: str) -> None:
    """Remove .security-reviewed-* files except current."""
    keep_name = f".security-reviewed-{keep_hash}"
    for f in smm_dir.glob(".security-reviewed-*"):
        if f.name == keep_name:
            continue
        # Validate suffix is a commit hash before deleting
        suffix = f.name.removeprefix(".security-reviewed-")
        if _COMMIT_HASH_RE.match(suffix):
            with contextlib.suppress(OSError):
                f.unlink()


def mark_security_reviewed(smm_dir: Path, cwd: str = ".") -> None:
    """Get HEAD hash and write security tracker. No-op on failure."""
    head_hash = get_head_hash(cwd)
    if head_hash is not None:
        write_security_tracker(smm_dir, head_hash)


def find_last_reviewed_hash(smm_dir: Path) -> str | None:
    """Find the commit hash from the most recent security tracker file."""
    for f in smm_dir.glob(".security-reviewed-*"):
        if f.is_symlink():
            continue
        suffix = f.name.removeprefix(".security-reviewed-")
        if _COMMIT_HASH_RE.match(suffix):
            return suffix
    return None


# Non-code suffixes shared with simplify_gate.py for consistent classification
_NON_CODE_SUFFIXES = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".adoc",
        ".tex",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".webp",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".csv",
        ".plist",
        ".pbxproj",
        ".xcworkspacedata",
        ".xcscheme",
        ".lock",
        ".license",
        ".gitignore",
        ".gitattributes",
        ".env",
        ".env.example",
        ".dockerignore",
    }
)

_NON_CODE_NAMES = frozenset(
    {"license", "changelog", "readme", "makefile", "dockerfile"}
)


def is_code_file(path: str) -> bool:
    """Return True if the file is likely code (not docs/config/images)."""
    suffix = Path(path).suffix.lower()
    if suffix in _NON_CODE_SUFFIXES:
        return False
    return Path(path).name.lower() not in _NON_CODE_NAMES


def diff_has_code_changes(reviewed_hash: str, head_hash: str, cwd: str = ".") -> bool:
    """Check if git diff between two commits contains code file changes.

    Returns True if any changed file passes is_code_file(). Returns True
    on error (fail-open would skip review; fail-closed is safer).
    """
    try:
        result = subprocess.check_output(
            ["git", "diff", "--name-only", f"{reviewed_hash}..{head_hash}"],
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            timeout=5,
        )
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return True  # fail-closed: assume code changes on error

    files = [f.strip() for f in result.strip().splitlines() if f.strip()]
    if not files:
        return False
    return any(is_code_file(f) for f in files)


# ---------------------------------------------------------------------------
# Enforcement mode
# ---------------------------------------------------------------------------

ENFORCEMENT_STRICT = "strict"
ENFORCEMENT_ADVISORY = "advisory"
_VALID_ENFORCEMENT_MODES = frozenset({ENFORCEMENT_STRICT, ENFORCEMENT_ADVISORY})


@functools.lru_cache(maxsize=1)
def load_enforcement_mode() -> str:
    """Load enforcement mode from settings.json, default 'strict'.

    Cached per process — each hook invocation is a separate process.
    Rejects symlinks (O_NOFOLLOW) and wrong-owner files.
    """
    try:
        settings_path = resolve_plugin_root() / "settings.json"
        # Reject symlinks and wrong-owner files
        fd = os.open(str(settings_path), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            if st.st_uid != os.getuid():
                return ENFORCEMENT_STRICT
            raw = os.read(fd, 65536).decode("utf-8")
        finally:
            os.close(fd)
        data = json.loads(raw)
        mode = data.get("enforcement", ENFORCEMENT_STRICT)
        if mode in _VALID_ENFORCEMENT_MODES:
            return mode
        return ENFORCEMENT_STRICT
    except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError, OSError):
        return ENFORCEMENT_STRICT


# ---------------------------------------------------------------------------
# Debt lookup
# ---------------------------------------------------------------------------


def find_debt_for_file(events: list[dict], file_path: str, cwd: str) -> list[dict]:
    """Filter debt events whose files array includes the target file."""
    normalized_target = normalize_path(file_path, cwd)
    return [
        e
        for e in events
        if e.get("type") == DEBT
        and isinstance(e.get("files", []), list)
        and _file_list_contains(e["files"], normalized_target, cwd)
    ]


# write_watermark imported from _append_impl at module level
