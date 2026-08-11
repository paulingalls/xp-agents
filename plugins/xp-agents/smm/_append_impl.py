#!/usr/bin/env python3
"""SMM atomic appender and CLI entry point.

Appends events atomically to events.jsonl using flock. Event construction
and validation are in event_builder.py and event_schema.py respectively.
"""

import contextlib
import fcntl
import json
import os
import signal

# Not used directly below — kept so `mock.patch("_append_impl.subprocess.…")`
# in tests/hooks/test_common_io.py and tests/smm/test_append_schema.py still
# resolves. `subprocess` is a singleton in sys.modules, so this binds the
# SAME module object `smm_dir_resolve._derive_smm_dir` calls through;
# patching via either name patches the one real module.
import subprocess  # noqa: F401
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Tags a concern with the close cycle it was raised during — called from
# `main()` only, never from `append_event`. See its module docstring.
import close_cycle_tag

# ---------------------------------------------------------------------------
# Event schema (re-exported from event_schema.py)
# ---------------------------------------------------------------------------
import marker_names

# Low-level atomic-write primitives (moved out to keep this file under the
# line-count cap; re-exported here BY IDENTITY so every existing
# `from _append_impl import write_text_atomic` etc. and every
# `_append_impl.write_text_atomic` reference resolves unchanged).
# LOCK_TIMEOUT_SECONDS/flock_with_timeout/read_with_lock stay below rather
# than moving too — see _append_lock.py's module docstring for why.
from _append_lock import (
    _ANSI_RE,
    _safe_open_nofollow,
    _strip_ansi,
    write_json_atomic,  # noqa: F401
    write_text_atomic,  # noqa: F401
    write_watermark,  # noqa: F401
)
from append_validation import validate_agent_id, validate_smm_dir
from event_builder import (
    build_event,
    build_parser,
    parse_json_arg,  # noqa: F401
)
from event_schema import (
    MAX_EVENT_BYTES,
    MAX_EVENTS_FILE_SIZE,
    PRIORITY_ASSUMED,  # noqa: F401
    PRIORITY_BLOCKING,  # noqa: F401
    PRIORITY_INFO,  # noqa: F401
    validate_event,
)

# Notifications: see resolution.py
from resolution import (  # noqa: F401
    _detect_platform,
    _notify_blocking_question,
    _sanitize_notification,
)

# ---------------------------------------------------------------------------
# SMM path resolution (moved out to keep this file under the line-count cap;
# re-exported here BY IDENTITY so every existing
# `from _append_impl import resolve_smm_dir` / `_append_impl.resolve_smm_dir`
# reference — including `mock.patch` sites — resolves unchanged).
# ---------------------------------------------------------------------------
from smm_dir_resolve import (  # noqa: F401
    _INIT_SH,
    _derive_smm_dir,
    now_iso,
    resolve_smm_dir,
)

# ---------------------------------------------------------------------------
# Locked atomic append
# ---------------------------------------------------------------------------


class LockTimeoutError(Exception):
    """Raised when flock cannot be acquired within the timeout."""

    pass


LOCK_TIMEOUT_SECONDS = 10

# Env override for the flock timeout, read fresh on every acquire. Exists so a
# gate that runs in a SUBPROCESS — which re-imports this module and never sees
# an in-process `mock.patch.object(LOCK_TIMEOUT_SECONDS)` — can still be made
# to time out fast in a test that needs a REAL cross-process contention
# (e.g. tests/integration/test_stop_gate_in_place.py's door-mutex test).
# Env vars are trusted in this codebase, so no further validation is needed
# beyond "parses as a positive int" — anything else (unset, empty, garbage,
# <= 0) falls back to LOCK_TIMEOUT_SECONDS, keeping production behavior
# unchanged when the var is absent.
_LOCK_TIMEOUT_ENV_VAR = "XP_LOCK_TIMEOUT_SECONDS"


def _effective_lock_timeout_seconds(default: int | None = None) -> int:
    """The acquire budget: env var, else *default*, else ``LOCK_TIMEOUT_SECONDS``.

    *default* is a CALLER's named budget (``flock_with_timeout(timeout_s=...)``),
    and it sits BELOW the env var deliberately. ``XP_LOCK_TIMEOUT_SECONDS`` is
    the only lever that reaches a subprocess — one re-imports this module and
    cannot see an in-process patch — so it has to be able to shorten every
    acquire, including one whose caller named its own budget. Were it the other
    way round, any caller passing ``timeout_s`` would become the one place a
    real cross-process contention test could not speed up.

    ``None`` (not a literal ``LOCK_TIMEOUT_SECONDS``) is the sentinel for "no
    named budget", because a literal default argument in the caller's signature
    would be evaluated at ``def`` time and freeze the module global at import —
    silently defeating the ``mock.patch.object`` seam ``_append_lock.py``'s
    docstring exists to protect.
    """
    raw = os.environ.get(_LOCK_TIMEOUT_ENV_VAR, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return default if default is not None else LOCK_TIMEOUT_SECONDS


def _make_alarm_handler(seconds: int):
    """A SIGALRM handler that reports the budget it was actually armed with.

    Captured rather than re-derived: rebuilding the number inside the handler
    read the module default, so a 2s acquire that timed out announced "within 10
    seconds" — a figure nothing had used, in the one line a human reads while
    diagnosing contention.
    """

    def _handler(signum: int, frame: object) -> None:
        raise LockTimeoutError(f"Could not acquire lock within {seconds} seconds")

    return _handler


@contextmanager
def flock_with_timeout(
    lock_path: Path, mode: int = fcntl.LOCK_EX, *, timeout_s: int | None = None
) -> Iterator[None]:
    """Acquire ``flock(mode)`` on ``lock_path`` under a SIGALRM timeout.

    Opens ``lock_path`` with ``O_NOFOLLOW`` (rejecting symlinks) and
    permission ``0o600``, arms ``SIGALRM`` for the resolved budget, takes
    the flock, yields, then on exit releases the lock and closes the fd.
    ``LOCK_UN`` is wrapped in ``contextlib.suppress(OSError)`` so a flaky
    release never masks an in-flight exception or blocks ``close``.
    Restores any prior ``SIGALRM`` handler.

    ``timeout_s`` names this caller's own budget — for a best-effort advisory
    file, where blocking a synchronous hook for the event log's 10s is its own
    problem. Omit it and the budget is ``LOCK_TIMEOUT_SECONDS`` exactly as
    before; ``XP_LOCK_TIMEOUT_SECONDS`` outranks both. See
    ``_effective_lock_timeout_seconds`` for why the precedence runs that way
    and why the default is a ``None`` sentinel rather than the global itself.

    Raises ``LockTimeoutError`` if the lock cannot be acquired within
    the budget; raises ``OSError`` if ``lock_path`` is a symlink.

    The lock fd is intentionally not yielded — every caller acquires
    its own fd against the data file (events.jsonl, sprint.json) and
    uses this lock purely as a serialization marker.
    """
    raw_fd = _safe_open_nofollow(lock_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    try:
        lock_fd = os.fdopen(raw_fd, "a")
    except BaseException:
        os.close(raw_fd)
        raise
    try:
        budget = _effective_lock_timeout_seconds(timeout_s)
        old_handler = signal.signal(signal.SIGALRM, _make_alarm_handler(budget))
        try:
            signal.alarm(budget)
            fcntl.flock(lock_fd, mode)
        finally:
            # Disarm in the FINALLY, not after the acquire: a `flock` error that
            # is not the alarm's own (ENOLCK/EOPNOTSUPP on a network mount,
            # EDEADLK) used to return with the alarm still counting and the
            # process default — TERMINATE — reinstalled below, killing the hook
            # seconds later with nothing written to `hook_errors.jsonl`.
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def read_with_lock(path: Path, *, max_size: int | None = MAX_EVENTS_FILE_SIZE) -> str:
    """Read file contents under shared flock.

    ``max_size`` caps the read: a file larger than it returns ``""`` (the
    default guards the hot append/compact path against a pathological log).
    Pass ``max_size=None`` to read the whole file regardless of size — repair
    and migrate MUST process the oversized/corrupt logs they exist to fix, for
    which the cap would silently no-op.

    Raises LockTimeoutError if the lock cannot be acquired within the
    flock budget. Raises OSError if the lock file is a symlink.
    """
    with flock_with_timeout(path.parent / "events.lock", fcntl.LOCK_SH):
        try:
            if max_size is not None and path.stat().st_size > max_size:
                return ""
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""


def append_event(smm_dir: Path, event: dict) -> None:
    """Append event as a single JSON line to events.jsonl with flock.

    Strips ANSI escape codes from content before writing.
    Raises LockTimeoutError if the lock cannot be acquired within the
    flock budget. Raises OSError if lock or events file is a symlink.
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

    with flock_with_timeout(lock_file):
        ev_fd = _safe_open_nofollow(events_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            with os.fdopen(ev_fd, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            os.close(ev_fd)
            raise

    # Notify on blocking questions — after write succeeds, never fails the write
    _notify_blocking_question(event)

    # Question gate for 🔴 questions — ACCUMULATES ids (newline-separated) so a
    # second blocking question raised before the answer does not clobber the
    # first: the answer resolves the whole co-pending batch, not just the last
    # id (question_answered.py consumes+resets the gate). Append mode is atomic
    # per write, so no read-modify-write race replaces the earlier overwrite.
    if event.get("type") == "question" and event.get("priority") == "\U0001f534":
        gate_fd = _safe_open_nofollow(
            smm_dir / marker_names.QUESTION_GATE,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        )
        try:
            with os.fdopen(gate_fd, "a", encoding="utf-8") as gate_f:
                gate_f.write(event.get("id", "") + "\n")
        except Exception:
            os.close(gate_fd)
            raise


def bulk_append(smm_dir: Path, events: list[dict]) -> None:
    """Append multiple events atomically with a single lock acquisition.

    Validates all events before acquiring the lock — fail-fast, no partial
    writes. Strips ANSI from content. Same safety guarantees as append_event().

    Raises ValueError if any event fails validation.
    Raises LockTimeoutError if the lock cannot be acquired within the
    flock budget.
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

    with flock_with_timeout(lock_file):
        ev_fd = _safe_open_nofollow(events_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            with os.fdopen(ev_fd, "wb") as f:
                for line in lines:
                    f.write(line)
        except Exception:
            os.close(ev_fd)
            raise

    # Notify on blocking questions — after write succeeds
    for event in cleaned:
        _notify_blocking_question(event)


# Whole-file rewriting (moved out to keep this file under its line-count band;
# re-exported here BY IDENTITY so every existing
# `from _append_impl import replace_events_file` and
# `_append_impl.replace_events_file` reference resolves unchanged). That module
# imports `flock_with_timeout` back from here LAZILY — see its docstring for why
# a module-level import would cycle.
from _events_replace import (  # noqa: E402  intentional post-definition re-export
    _preservable_id,  # noqa: F401
    event_ids,  # noqa: F401
    replace_events_file,  # noqa: F401
)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Validate agent_id
    try:
        validate_agent_id(args.agent)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve and validate SMM directory (argparse type=Path handles --smm-dir)
    smm_dir = args.smm_dir if args.smm_dir else resolve_smm_dir()
    if smm_dir is None:
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)
    try:
        validate_smm_dir(smm_dir)
    except ValueError as e:
        print(f"Error: {e}\nRun smm/init.sh first.", file=sys.stderr)
        sys.exit(1)

    # Build event
    event = build_event(args)

    # Tag a concern with the close cycle that is running, BEFORE validation: a
    # stamped event that would not validate must never reach the log. CLI path
    # only — see close_cycle_tag's docstring for why not `append_event`.
    close_cycle_tag.stamp(smm_dir, event)

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

    # Print the assigned event id to stdout so callers (e.g. close-reviewer
    # agent populating `Resolves-Event:` trailers) can capture it via
    # `id=$(append.sh ...)`. Stdout contract: exactly the event id, nothing
    # else — the duplicate-debt probe below MUST keep its output on stderr.
    print(event["id"])

    # Post-write duplicate-debt probe — advisory only, never fails the write
    try:
        scripts_dir = Path(__file__).parent.parent / "scripts"
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        import duplicate_debt_probe

        duplicate_debt_probe.run_probe_and_append(smm_dir, event)
    except Exception:
        pass


if __name__ == "__main__":
    main()
