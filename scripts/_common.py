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

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BlockedError(Exception):
    """Raised when a tool call should be blocked (exit 2 with stderr message)."""


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
# Watermark management
# ---------------------------------------------------------------------------


def validate_smm_dir(smm_dir: Path) -> None:
    """Validate SMM directory exists, is owned by us, not world-writable."""
    if not smm_dir.exists():
        raise ValueError(f"SMM directory does not exist: {smm_dir}")
    st = smm_dir.stat()
    if st.st_uid != os.getuid():
        raise ValueError(f"SMM directory not owned by current user: {smm_dir}")
    if st.st_mode & 0o002:
        raise ValueError(f"SMM directory is world-writable: {smm_dir}")


def try_validate_smm_dir(smm_dir: Path | None) -> Path | None:
    """Validate SMM dir, returning None on failure instead of raising."""
    if smm_dir is None:
        return None
    try:
        validate_smm_dir(smm_dir)
        return smm_dir
    except ValueError:
        return None


_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_:\-]+$")


def _validate_agent_id(agent_id: str) -> None:
    """Reject agent IDs that don't match the allowlist pattern."""
    if not agent_id:
        raise ValueError("agent_id must not be empty")
    if not _AGENT_ID_RE.match(agent_id):
        raise ValueError(f"Invalid agent_id: {agent_id!r}")


def normalize_path(file_path: str, cwd: str) -> str:
    """Resolve a file path against cwd, return normalized string."""
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(cwd) / p
    return os.path.normpath(str(p))


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


def append_safe(smm_dir: Path, event: dict) -> None:
    """Validate and append event, swallowing lock errors."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))
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
    return make_event("concern", agent_id, content, severity=severity)


def detect_conflicts(
    events: list[dict],
    agent_id: str,
    file_path: str | None = None,
    cwd: str | None = None,
) -> list[dict]:
    """Detect structural conflicts in the event log. Returns concern event dicts.

    When file_path/cwd are None, skip pattern 1 (overlapping working_on).
    """
    concerns: list[dict] = []

    # 1. Overlapping working_on — another agent claims same file
    if file_path is not None and cwd is not None:
        normalized = normalize_path(file_path, cwd)
        agent_files: dict[str, list[str]] = {}
        for e in events:
            if e.get("type") == "status" and e.get("working_on"):
                agent_files[e.get("agent_id", "")] = e["working_on"]

        for aid, files in agent_files.items():
            if aid == agent_id:
                continue
            norm_files = {normalize_path(f, cwd) for f in files}
            if normalized in norm_files:
                concerns.append(
                    make_concern(
                        f"Overlapping working_on: agent '{aid}' is also working on "
                        f"'{file_path}'. Coordinate to avoid conflicts.",
                        "medium",
                        agent_id,
                    )
                )

    # 2. Assumption contradicted by discovery
    assumptions: dict[str, dict] = {}
    for e in events:
        if e.get("type") == "assumption":
            assumptions[e.get("id", "")] = e
        elif e.get("type") == "discovery":
            for ref in e.get("references", []):
                if ref in assumptions:
                    concerns.append(
                        make_concern(
                            f"Assumption contradicted: '{assumptions[ref]['content']}' "
                            f"contradicted by discovery '{e['content']}'.",
                            "high",
                            agent_id,
                        )
                    )

    # 3. Convention violation — decision diverges from convention on same topic
    conventions_by_topic: dict[str, list[dict]] = {}
    for e in events:
        if e.get("type") == "convention":
            topic = e.get("topic", "")
            conventions_by_topic.setdefault(topic, []).append(e)

    for e in events:
        if e.get("type") == "decision":
            topic = e.get("topic", "")
            if topic in conventions_by_topic:
                refs = set(e.get("references", []))
                conv_ids = {c["id"] for c in conventions_by_topic[topic]}
                if not refs & conv_ids:
                    concerns.append(
                        make_concern(
                            f"Convention violation: decision on '{topic}' "
                            "diverges from established convention.",
                            "medium",
                            agent_id,
                        )
                    )

    # 4. Stale question — 🔴 question with no answer after 20+ subsequent events
    question_positions: dict[str, int] = {}
    answered_ids: set[str] = set()
    for i, e in enumerate(events):
        if e.get("type") == "question" and e.get("priority") == "\U0001f534":
            question_positions[e.get("id", "")] = i
        elif e.get("type") == "answer":
            for ref in e.get("references", []):
                answered_ids.add(ref)

    total = len(events)
    for qid, pos in question_positions.items():
        if qid not in answered_ids and (total - pos - 1) >= 20:
            concerns.append(
                make_concern(
                    f"Stale question: blocking question (id {qid[:8]}) has had "
                    f"{total - pos - 1} events without an answer.",
                    "medium",
                    agent_id,
                )
            )

    # 5. Superseded decision — two decisions on same topic with no concern between
    decisions_by_topic: dict[str, list[tuple[int, dict]]] = {}
    concern_pos_list: list[int] = []
    for i, e in enumerate(events):
        if e.get("type") == "decision":
            topic = e.get("topic", "")
            decisions_by_topic.setdefault(topic, []).append((i, e))
        elif e.get("type") == "concern":
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
                concerns.append(
                    make_concern(
                        f"Superseded decision: topic '{topic}' has multiple decisions "
                        f"without an intervening concern.",
                        "low",
                        agent_id,
                    )
                )

    return concerns


# ---------------------------------------------------------------------------
# Semantic reference enrichment (shared by post_tool_use.py and plan_review.py)
# ---------------------------------------------------------------------------


def find_related_decisions(events: list[dict], file_path: str, cwd: str) -> list[str]:
    """Find event IDs of decisions/conventions that reference this file."""
    normalized = normalize_path(file_path, cwd)
    related: list[str] = []

    for e in events:
        if e.get("type") not in ("decision", "convention"):
            continue
        # Check working_on field
        working_on = e.get("working_on", [])
        if isinstance(working_on, list):
            norm_wo = {normalize_path(f, cwd) for f in working_on}
            if normalized in norm_wo:
                related.append(e["id"])
                continue
        # Check references field for normalized path matches
        refs = e.get("references", [])
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, str):
                    try:
                        if normalize_path(ref, cwd) == normalized:
                            related.append(e["id"])
                            break
                    except (ValueError, OSError):
                        continue

    return related


def write_watermark(smm_dir: Path, agent_id: str, count: int) -> None:
    """Atomic watermark write via tempfile + rename. Validates agent_id."""
    _validate_agent_id(agent_id)
    wm_file = smm_dir / f".watermark-{agent_id}"

    fd, tmp = tempfile.mkstemp(dir=smm_dir, prefix=f".wm-{agent_id}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(str(count))
        os.chmod(tmp, 0o600)
        os.rename(tmp, wm_file)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
