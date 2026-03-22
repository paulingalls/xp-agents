#!/usr/bin/env python3
"""SMM atomic appender and CLI entry point.

Appends events atomically to events.jsonl using flock. Event construction
and validation are in event_builder.py and event_schema.py respectively.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# SMM path resolution
# ---------------------------------------------------------------------------


def resolve_smm_dir() -> Path:
    """Derive the SMM directory from git-common-dir, matching init.sh logic."""
    try:
        git_common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    # Resolve to absolute path
    git_common_path = Path(git_common)
    if not git_common_path.is_absolute():
        git_common_path = git_common_path.resolve()

    project_id = hashlib.sha256(str(git_common_path).encode()).hexdigest()[:12]
    # Use CLAUDE_PLUGIN_DATA if available (standard plugin ecosystem path),
    # fall back to ~/.claude/xp-agents for --plugin-dir development mode.
    base_dir = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if not base_dir:
        base_dir = str(Path.home() / ".claude" / "xp-agents")
    return Path(base_dir) / project_id / "smm"


# ---------------------------------------------------------------------------
# Agent ID validation
# ---------------------------------------------------------------------------

_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_:\-]+$")


def _validate_smm_dir(smm_dir: Path) -> None:
    """Validate SMM directory exists, is owned by us, not world-writable."""
    if not smm_dir.exists():
        raise ValueError(f"SMM directory does not exist: {smm_dir}")
    st = smm_dir.stat()
    if st.st_uid != os.getuid():
        raise ValueError(f"SMM directory not owned by current user: {smm_dir}")
    if st.st_mode & 0o002:
        raise ValueError(f"SMM directory is world-writable: {smm_dir}")


def _validate_agent_id(agent_id: str) -> None:
    """Reject agent IDs that don't match the allowlist pattern."""
    if not agent_id:
        raise ValueError("agent_id must not be empty")
    if not _AGENT_ID_RE.match(agent_id):
        raise ValueError(f"Invalid agent_id: {agent_id!r}")


# ---------------------------------------------------------------------------
# Event schema (re-exported from event_schema.py)
# ---------------------------------------------------------------------------

from event_builder import (  # noqa: E402
    build_event,
    build_parser,
    parse_json_arg,  # noqa: F401
)
from event_schema import (  # noqa: E402
    MAX_EVENT_BYTES,
    MAX_EVENTS_FILE_SIZE,
    PRIORITY_ASSUMED,  # noqa: F401
    PRIORITY_BLOCKING,  # noqa: F401
    PRIORITY_INFO,  # noqa: F401
    validate_event,
)

# Resolution tracking: see resolution.py
from resolution import compute_resolutions  # noqa: F401, E402

# ---------------------------------------------------------------------------
# Shared JSONL parsing
# ---------------------------------------------------------------------------


def parse_jsonl(raw: str) -> tuple[list[dict], int]:
    """Parse JSONL text into dicts. Returns (events, skipped_count).

    Skips blank lines, malformed JSON, and non-dict values silently.
    This is the canonical JSONL parser — all callers should use it.
    """
    events: list[dict] = []
    skipped = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                events.append(obj)
            else:
                skipped += 1
        except json.JSONDecodeError:
            skipped += 1
    return events, skipped


# Notifications: see resolution.py
from resolution import (  # noqa: F401, E402
    _detect_platform,
    _notify_blocking_question,
    _sanitize_notification,
)

# ---------------------------------------------------------------------------
# Locked atomic append
# ---------------------------------------------------------------------------


class LockTimeoutError(Exception):
    """Raised when flock cannot be acquired within the timeout."""

    pass


def _on_alarm(signum: int, frame: object) -> None:
    raise LockTimeoutError("Could not acquire lock within 2 seconds")


def _safe_open_nofollow(path: Path, flags: int) -> int:
    """Open a file with O_NOFOLLOW to reject symlinks."""
    return os.open(str(path), flags | os.O_NOFOLLOW, 0o600)


def read_with_lock(path: Path) -> str:
    """Read file contents under shared flock with 2-second timeout.

    Raises LockTimeoutError if the lock cannot be acquired.
    Raises OSError if the lock file is a symlink.
    """
    lock_path = path.parent / "events.lock"
    lock_fd = None
    raw_fd = None

    try:
        raw_fd = os.open(
            str(lock_path),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None

        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        try:
            if path.stat().st_size > MAX_EVENTS_FILE_SIZE:
                return ""
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


def write_watermark(smm_dir: Path, agent_id: str, line_count: int) -> None:
    """Atomic write of watermark via temp + rename. Validates agent_id.

    Rejects symlinks at the target path to prevent write-through attacks.
    """
    _validate_agent_id(agent_id)
    wm_file = smm_dir / f".watermark-{agent_id}"

    # Reject existing symlink at target path
    if wm_file.is_symlink():
        raise OSError(f"Watermark path is a symlink: {wm_file}")

    write_text_atomic(wm_file, str(line_count))


def write_text_atomic(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Atomic write of text content via tempfile + rename.

    Creates tempfile in same directory as target, writes content,
    sets permissions to 0o600, then atomically renames.
    """
    target_dir = path.parent
    fd, tmp = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.chmod(tmp, 0o600)
        os.rename(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_json_atomic(path: Path, data: dict) -> None:
    """Atomic write of JSON data via tempfile + rename."""
    write_text_atomic(path, json.dumps(data))


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)


def append_event(smm_dir: Path, event: dict) -> None:
    """Append event as a single JSON line to events.jsonl with flock.

    Strips ANSI escape codes from content before writing.
    Raises LockTimeoutError if the lock cannot be acquired within 2 seconds.
    Raises OSError if lock or events file is a symlink.
    """
    # Strip ANSI escape codes from content to prevent garbage in the log
    if "content" in event:
        event["content"] = _strip_ansi(event["content"])

    events_file = smm_dir / "events.jsonl"
    lock_file = smm_dir / "events.lock"
    line = json.dumps(event, ensure_ascii=False) + "\n"

    if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
        raise ValueError(
            f"Serialized event too large "
            f"({len(line.encode('utf-8'))} > {MAX_EVENT_BYTES} bytes)"
        )

    lock_fd = None
    raw_fd = None

    try:
        raw_fd = _safe_open_nofollow(lock_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None  # now owned by lock_fd

        # Use blocking flock with SIGALRM timeout (2 seconds)
        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        ev_fd = _safe_open_nofollow(events_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            with os.fdopen(ev_fd, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            os.close(ev_fd)
            raise

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    # Notify on blocking questions — after write succeeds, never fails the write
    _notify_blocking_question(event)


def bulk_append(smm_dir: Path, events: list[dict]) -> None:
    """Append multiple events atomically with a single lock acquisition.

    Validates all events before acquiring the lock — fail-fast, no partial
    writes. Strips ANSI from content. Same safety guarantees as append_event().

    Raises ValueError if any event fails validation.
    Raises LockTimeoutError if the lock cannot be acquired within 2 seconds.
    """
    if not events:
        return

    # Strip ANSI without mutating caller's dicts
    cleaned = []
    for event in events:
        if "content" in event and _ANSI_RE.search(event["content"]):
            event = {**event, "content": _strip_ansi(event["content"])}
        cleaned.append(event)

    # Validate all events up front — fail before acquiring lock
    for event in cleaned:
        errors = validate_event(event)
        if errors:
            raise ValueError(f"Invalid event: {'; '.join(errors)}")

    # Serialize all lines
    lines: list[bytes] = []
    for event in cleaned:
        line = json.dumps(event, ensure_ascii=False) + "\n"
        encoded = line.encode("utf-8")
        if len(encoded) > MAX_EVENT_BYTES:
            raise ValueError(
                f"Serialized event too large ({len(encoded)} > {MAX_EVENT_BYTES} bytes)"
            )
        lines.append(encoded)

    # Single lock acquisition, write all lines
    events_file = smm_dir / "events.jsonl"
    lock_file = smm_dir / "events.lock"
    lock_fd = None
    raw_fd = None

    try:
        raw_fd = _safe_open_nofollow(lock_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None

        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        ev_fd = _safe_open_nofollow(events_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            with os.fdopen(ev_fd, "wb") as f:
                for line in lines:
                    f.write(line)
        except Exception:
            os.close(ev_fd)
            raise

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    # Notify on blocking questions — after write succeeds
    for event in cleaned:
        _notify_blocking_question(event)


def replace_events_file(smm_dir: Path, events: list[dict]) -> str:
    """Read events.jsonl under exclusive flock, replace atomically.

    Holds the exclusive lock for the entire read-then-write transaction
    to prevent TOCTOU races. Returns the original file contents (for
    callers that need to back up the original).

    Raises LockTimeoutError if the lock cannot be acquired.
    """
    events_file = smm_dir / "events.jsonl"
    lock_file = smm_dir / "events.lock"
    lock_fd = None
    raw_fd = None
    original_content = ""

    try:
        raw_fd = _safe_open_nofollow(lock_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            lock_fd = os.fdopen(raw_fd, "a")
        except Exception:
            os.close(raw_fd)
            raise
        raw_fd = None

        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(2)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)

        # Read original under lock (prevents TOCTOU race)
        try:
            original_content = events_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            original_content = ""

        # Write replacement via tempfile + rename
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        fd, tmp = tempfile.mkstemp(dir=smm_dir, suffix=".jsonl.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + ("\n" if lines else ""))
            os.chmod(tmp, 0o600)
            os.rename(tmp, events_file)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    return original_content


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Validate agent_id
    try:
        _validate_agent_id(args.agent)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve and validate SMM directory
    smm_dir = args.smm_dir if args.smm_dir else resolve_smm_dir()
    try:
        _validate_smm_dir(smm_dir)
    except ValueError as e:
        print(f"Error: {e}\nRun smm/init.sh first.", file=sys.stderr)
        sys.exit(1)

    # Build event
    event = build_event(args)

    # Validate
    errors = validate_event(event)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    # Append
    try:
        append_event(smm_dir, event)
    except LockTimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
