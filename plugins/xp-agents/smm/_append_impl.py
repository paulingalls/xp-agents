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
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """Current UTC time as an ISO 8601 string.

    Canonical source for the ``datetime.now(timezone.utc).isoformat()``
    pattern. ``event_builder.build_event`` keeps its own inline call:
    ``_append_impl`` imports ``event_builder`` at module top level (see
    the ``from event_builder import ...`` block below), so adding a
    top-level ``from _append_impl import now_iso`` in ``event_builder``
    would close the cycle. When a caller imports ``event_builder``
    first (e.g. ``smm_store``, ``session_end``, ``duplicate_debt_probe``),
    Python would re-enter ``_append_impl`` mid-init and raise
    ``ImportError: cannot import name 'build_event' from partially
    initialized module``. All other call sites route through
    ``now_iso``, so a future timestamp policy change is a near-one-line
    edit.
    """
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# SMM path resolution
# ---------------------------------------------------------------------------


_INIT_SH = Path(__file__).parent / "init.sh"


def resolve_smm_dir() -> Path | None:
    """Return the SMM directory, or None if it can't be resolved.

    Honors $SMM_DIR env var as the single canonical handle — lets teammate
    spawners propagate the lead's SMM across process boundaries. When unset,
    delegates to ``_derive_smm_dir`` which runs init.sh.

    The env-var read happens on every call (cheap), so test isolation that
    pins SMM_DIR per test takes effect immediately. ``_derive_smm_dir`` is
    not cached: caching across calls in a single process is unsafe when the
    derivation depends on cwd/env that tests may mutate, and in production
    each hook is a fresh `python3` invocation so a process-local cache
    never had a hit anyway.
    """
    env_smm = os.environ.get("SMM_DIR", "").strip()
    if env_smm:
        return Path(env_smm)
    return _derive_smm_dir()


def _derive_smm_dir() -> Path | None:
    """Run init.sh to derive SMM dir from project state."""
    try:
        out = subprocess.check_output(
            ["bash", str(_INIT_SH)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return Path(out) if out else None


# ---------------------------------------------------------------------------
# Event schema (re-exported from event_schema.py)
# ---------------------------------------------------------------------------

import marker_names  # noqa: E402

# Low-level atomic-write primitives (moved out to keep this file under the
# line-count cap; re-exported here BY IDENTITY so every existing
# `from _append_impl import write_text_atomic` etc. and every
# `_append_impl.write_text_atomic` reference resolves unchanged).
# LOCK_TIMEOUT_SECONDS/flock_with_timeout/read_with_lock stay below rather
# than moving too — see _append_lock.py's module docstring for why.
from _append_lock import (  # noqa: E402
    _ANSI_RE,
    _safe_open_nofollow,
    _strip_ansi,
    write_json_atomic,  # noqa: F401
    write_text_atomic,  # noqa: F401
    write_watermark,  # noqa: F401
)
from append_validation import validate_agent_id, validate_smm_dir  # noqa: E402
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


def _effective_lock_timeout_seconds() -> int:
    """``LOCK_TIMEOUT_SECONDS``, overridable via ``XP_LOCK_TIMEOUT_SECONDS``."""
    raw = os.environ.get(_LOCK_TIMEOUT_ENV_VAR, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return LOCK_TIMEOUT_SECONDS


def _on_alarm(signum: int, frame: object) -> None:
    raise LockTimeoutError(
        f"Could not acquire lock within {_effective_lock_timeout_seconds()} seconds"
    )


@contextmanager
def flock_with_timeout(lock_path: Path, mode: int = fcntl.LOCK_EX) -> Iterator[None]:
    """Acquire ``flock(mode)`` on ``lock_path`` under a SIGALRM timeout.

    Opens ``lock_path`` with ``O_NOFOLLOW`` (rejecting symlinks) and
    permission ``0o600``, arms ``SIGALRM`` for ``LOCK_TIMEOUT_SECONDS``
    seconds (overridable per-process via the ``XP_LOCK_TIMEOUT_SECONDS``
    env var — see ``_effective_lock_timeout_seconds``), takes the flock,
    yields, then on exit releases the lock and closes the fd. ``LOCK_UN``
    is wrapped in ``contextlib.suppress(OSError)`` so a flaky release
    never masks an in-flight exception or blocks ``close``. Restores any
    prior ``SIGALRM`` handler.

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
        old_handler = signal.signal(signal.SIGALRM, _on_alarm)
        try:
            signal.alarm(_effective_lock_timeout_seconds())
            fcntl.flock(lock_fd, mode)
            signal.alarm(0)
        finally:
            signal.signal(signal.SIGALRM, old_handler)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def read_with_lock(path: Path) -> str:
    """Read file contents under shared flock.

    Raises LockTimeoutError if the lock cannot be acquired within the
    flock budget. Raises OSError if the lock file is a symlink.
    """
    with flock_with_timeout(path.parent / "events.lock", fcntl.LOCK_SH):
        try:
            if path.stat().st_size > MAX_EVENTS_FILE_SIZE:
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


def event_ids(events: list[dict]) -> set[str]:
    """The ids of *events* — the `seen_ids` a whole-file rewriter must pass.

    Skips entries with no usable string id; `parse_jsonl` admits any dict, so
    a hand-edited line can reach a caller without one. Such an entry is still
    written if the caller retained it — it is only unmatchable when scanning
    the file, which is what the id-less DROP rule in `replace_events_file`
    covers.
    """
    return {e["id"] for e in events if isinstance(e.get("id"), str)}


def _preservable_id(line: str) -> str | None:
    """The id of a file line that a rewriter could have SEEN, else None.

    None means the line is not preservable and is dropped: it is malformed, is
    not an object, or carries no string id. Dropping it is SAFE because of that
    missing id — every event built for `append_event` gets a `generate_id()`
    id, so an id-less line was never a concurrent arrival. The guarantee is the
    BUILDERS', not validation's: `append_event` does not call `validate_event`
    and neither do all of its callers, so an append path that can omit `id`
    would break this rule. Dropping is also NECESSARY: an unpreservable line
    can never be in any `seen_ids`, so a naive preserve-the-unseen rule would
    keep it forever and `repair` could never delete a malformed line again.
    """
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    event_id = obj.get("id")
    return event_id if isinstance(event_id, str) else None


def replace_events_file(
    smm_dir: Path, events: list[dict], *, seen_ids: set[str]
) -> str:
    """Read events.jsonl under exclusive flock, replace atomically.

    *events* is the caller's snapshot of what should survive — but the caller
    read it WITHOUT the exclusive lock, so the file may have grown since. An
    event appended in that window is in neither the snapshot nor the archive
    the caller built from it; writing the snapshot verbatim would erase it
    with no trace anywhere. So the read this function already does under the
    lock is not thrown away: it is merged.

    *seen_ids* is what makes the merge decidable — the ids the caller actually
    LOOKED AT. Every file line is then one of four things:

      * seen and retained     -> written (the caller's copy, so a rewriter such
                                 as `migrate` keeps its transformation)
      * seen and NOT retained -> dropped, deliberately (archived, invalid, a
                                 duplicate) — the fix must not resurrect these
      * NOT seen              -> PRESERVED at the tail: an event the caller
                                 never saw was never a candidate for removal
      * unpreservable         -> dropped; see `_preservable_id`

    Keyword-only and REQUIRED on purpose: a caller that forgets it is a
    TypeError, not a silent return to eating events.

    Preserved lines are written back BYTE-FOR-BYTE rather than re-serialized —
    this function has no business rewriting an event it does not understand.

    Returns the original file contents (for callers that back up the original).
    Raises LockTimeoutError if the lock cannot be acquired.
    """
    events_file = smm_dir / "events.jsonl"
    lock_file = smm_dir / "events.lock"
    original_content = ""

    with flock_with_timeout(lock_file):
        # Read original under lock (prevents TOCTOU race)
        try:
            original_content = events_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            original_content = ""

        # Events that arrived while the caller was deciding — keep them.
        unseen: list[str] = [
            stripped
            for line in original_content.splitlines()
            if (stripped := line.strip())
            and (event_id := _preservable_id(stripped)) is not None
            and event_id not in seen_ids
        ]

        # Write replacement via tempfile + rename
        lines = [json.dumps(e, ensure_ascii=False) for e in events] + unseen
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

    return original_content


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
