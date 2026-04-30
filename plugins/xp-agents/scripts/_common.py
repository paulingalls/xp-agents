#!/usr/bin/env python3
"""Shared helpers for all hook scripts.

DRY module providing SMM resolution, hook I/O, recursion prevention,
event reading, and watermark management.
"""

import json
import os
import shlex
import sys
from pathlib import Path, PurePosixPath

# Make smm/ importable so we can use _append_impl as the foundational module
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import (
    PRIORITY_ASSUMED,  # noqa: F401
    PRIORITY_BLOCKING,  # noqa: F401
    PRIORITY_INFO,  # noqa: F401
    _validate_agent_id,  # noqa: F401
    now_iso,
    parse_jsonl,
    write_watermark,  # noqa: F401
)
from _append_impl import _validate_smm_dir as validate_smm_dir
from _append_impl import resolve_smm_dir as _resolve_smm_dir_impl
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
SPRINT = "sprint"
RETROSPECTIVE = "retrospective"

# Shared data-file name used across the retrospective subsystem:
# written by scripts/retrospective.py, consumed by the xp-retrospective
# agent, cleaned up by scripts/save_retrospective.py.
RETRO_INPUT_FILENAME = ".retro-input.json"


def current_session_start_index(events: list[dict]) -> int:
    """Return index of the first event in the current session.

    Current session = events after the last SESSION_END event. Returns 0
    when no SESSION_END has been recorded (everything is the current
    session). Reverse-scan so complexity is O(events-since-last-end).
    """
    for i in range(len(events) - 1, -1, -1):
        if events[i].get("type") == SESSION_END:
            return i + 1
    return 0


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


def resolve_smm_dir() -> Path | None:
    """Return the SMM directory or None. Delegates to _append_impl.

    Caching lives in _append_impl on the slow part only (init.sh subprocess
    via _derive_smm_dir). The env-var read happens on every call so tests
    that pin SMM_DIR see fresh values without manual cache busts.

    Note: when $SMM_DIR is unset and derivation runs, init.sh creates/seeds
    the SMM directory if it doesn't exist (first-call side effect). When
    $SMM_DIR is set, the env value is returned as-is with no I/O.
    """
    return _resolve_smm_dir_impl()


# ---------------------------------------------------------------------------
# Hook I/O
# ---------------------------------------------------------------------------


_MAX_STDIN_SIZE = 10_485_760  # 10 MB — large enough to absorb lefthook output
_HOOK_ERROR_LINE_MAX = 2048  # cap each line so a single O_APPEND write stays atomic
_HOOK_ERROR_FILE = "hook_errors.jsonl"


def _truncate_for_log(value: object, max_len: int = 200) -> str:
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "...[truncated]"


def truncate(text: str, max_len: int) -> str:
    """Truncate ``text`` to ``max_len`` chars, terminating with ``...``.

    Caller must pass ``max_len`` — there is no default because consumers
    differ (prompt nuggets cap at 120; customer-input echoes cap at 500),
    and a silent default would change behavior on a future shared use.
    For the structured ``hook_errors.jsonl`` writer, see
    ``_truncate_for_log`` — it uses ``...[truncated]`` to signal the
    cap was hit in machine-readable log lines.
    """
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _log_hook_error(reason: str, error_class: str, **ctx: object) -> None:
    """Best-effort diagnostic log for silent-failure paths.

    Mirrors to stderr always; appends a JSON line to ``${SMM_DIR}/hook_errors.jsonl``
    when SMM_DIR is set. Each line is capped at 2 KB and written via a single
    ``os.write`` to a file opened with O_APPEND, so concurrent writers do not
    interleave their output. Never raises — silent failures get a trace, not a
    crash.
    """
    entry: dict = {
        "ts": now_iso(),
        "script": Path(sys.argv[0]).name if sys.argv else "<unknown>",
        "reason": _truncate_for_log(reason, 500),
        "error_class": error_class,
    }
    if ctx:
        entry["context"] = {k: _truncate_for_log(v) for k, v in ctx.items()}
    line = json.dumps(entry, ensure_ascii=False)
    encoded = line.encode("utf-8")
    if len(encoded) > _HOOK_ERROR_LINE_MAX:
        # Paranoid backstop: drop context, keep core fields.
        entry.pop("context", None)
        line = json.dumps(entry, ensure_ascii=False)
        encoded = line.encode("utf-8")
    print(f"hook_error: {line}", file=sys.stderr)
    # resolve_smm_dir delegates to init.sh when SMM_DIR is unset — without it,
    # cache-derived hook invocations would lose the diagnostic trace. Returns
    # None outside a git repo, in which case the stderr mirror is the only
    # surface.
    smm_dir = resolve_smm_dir()
    if smm_dir is None:
        return
    try:
        path = smm_dir / _HOOK_ERROR_FILE
        fd = os.open(
            str(path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, encoded + b"\n")
        finally:
            os.close(fd)
    except OSError:
        pass


def read_hook_input() -> dict:
    """Read JSON from stdin with size limit. On error: log + exit 0 (graceful)."""
    raw = ""
    try:
        raw = sys.stdin.read(_MAX_STDIN_SIZE + 1)
        if len(raw) > _MAX_STDIN_SIZE:
            _log_hook_error(
                f"stdin exceeded {_MAX_STDIN_SIZE} bytes",
                error_class="stdin_oversize",
                size=len(raw),
            )
            sys.exit(0)
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        _log_hook_error(
            f"stdin parse failed: {e}",
            error_class=type(e).__name__,
            head=raw[:200],
        )
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


def load_events_with_resolutions(
    smm_dir: Path,
) -> tuple[list[dict], dict]:
    """Read events.jsonl and compute resolutions in one call."""
    import resolution

    events = read_events_raw(smm_dir)
    return events, resolution.compute_resolutions(events)


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


def extract_file_path(tool_name: str, tool_input: dict) -> str | None:
    """Extract file_path from tool_input for write tools."""
    if tool_name in ("Write", "Edit", "MultiEdit"):
        return tool_input.get("file_path")
    return None


def make_event(event_type: str, agent_id: str, content: str, **extra) -> dict:
    """Build a minimal SMM event dict with standard fields."""
    from event_builder import extract_refs_suffix, generate_id

    event = {
        "id": generate_id(),
        "ts": now_iso(),
        "type": event_type,
        "agent_id": agent_id,
        "content": content,
        "schema_version": 1,
    }
    event.update(extra)
    extract_refs_suffix(event)
    return event


def count_unresolved_concerns(events: list[dict]) -> int:
    """Count concern events that have no resolution."""
    import resolution

    concern_ids = {e["id"] for e in events if e.get("type") == CONCERN and e.get("id")}
    if not concern_ids:
        return 0
    resolved = resolution.compute_resolutions(events)["resolved_concern_ids"]
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


def _run_duplicate_debt_probe(smm_dir: Path, event: dict) -> None:
    """Post-write probe: if event is debt, check for near-duplicates."""
    try:
        import duplicate_debt_probe

        duplicate_debt_probe.run_probe_and_append(smm_dir, event)
    except ImportError:
        pass


def append_safe(smm_dir: Path, event: dict) -> None:
    """Validate and append event. LockTimeoutError is logged + swallowed."""
    import _append_impl

    errors = _append_impl.validate_event(event)
    if not errors:
        try:
            _append_impl.append_event(smm_dir, event)
        except _append_impl.LockTimeoutError as e:
            _log_hook_error(
                f"append_safe dropped event: {e}",
                error_class=type(e).__name__,
                event_id=event.get("id"),
                event_type=event.get("type"),
            )
        else:
            _run_duplicate_debt_probe(smm_dir, event)


def parse_append_sh_args(command: str) -> dict[str, str]:
    """Parse an append.sh invocation into {flag_name: flag_value}.

    Returns an empty dict when the command is not an append.sh call or
    cannot be tokenized. Uses shlex so any quoting shape round-trips cleanly.

    Cheap substring gate first: this hook fires on every Bash command,
    and shlex.split on a 10k-char heredoc is wasteful when we can skip.
    The token match checks the filename exactly (via PurePosixPath.name)
    so sibling scripts like `fake-append.sh` do not false-positive.
    """
    if "append.sh" not in command:
        return {}
    try:
        tokens = shlex.split(command)
    except ValueError:
        return {}
    for i, tok in enumerate(tokens):
        if PurePosixPath(tok).name == "append.sh":
            rest = tokens[i + 1 :]
            break
    else:
        return {}
    result: dict[str, str] = {}
    j = 0
    while j < len(rest):
        t = rest[j]
        if not t.startswith("--"):
            j += 1
            continue
        # Boolean flag: next token is another --flag or we're at the end.
        if j + 1 >= len(rest) or rest[j + 1].startswith("--"):
            result[t[2:]] = ""
            j += 1
        else:
            result[t[2:]] = rest[j + 1]
            j += 2
    return result


def bulk_append_safe(smm_dir: Path, events: list[dict]) -> None:
    """Filter invalid events, then bulk-append valid ones atomically.

    LockTimeoutError and ValueError are logged + swallowed: the underlying
    write is best-effort (the caller is a hook that must not crash) but
    every dropped batch leaves a structured trace in hook_errors.jsonl.
    """
    import _append_impl

    valid = [e for e in events if not _append_impl.validate_event(e)]
    if not valid:
        return
    try:
        _append_impl.bulk_append(smm_dir, valid)
    except (_append_impl.LockTimeoutError, ValueError) as e:
        _log_hook_error(
            f"bulk_append_safe dropped {len(valid)} event(s): {e}",
            error_class=type(e).__name__,
            event_types_sample=[ev.get("type") for ev in valid[:5]],
        )
    else:
        for event in valid:
            _run_duplicate_debt_probe(smm_dir, event)


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
