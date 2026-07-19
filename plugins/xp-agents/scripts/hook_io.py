#!/usr/bin/env python3
"""Hook I/O protocol helpers.

Split out of _common.py (which re-exports these names by identity) to keep
both files under the 500-line cap. Covers stdin/stdout hook protocol
(read_hook_input/hook_output/block_output), the blocking-signal exception
(BlockedError), and the diagnostic logger for silent-failure paths
(log_hook_error) plus its truncation helpers.
"""

import json
import os
import sys
from pathlib import Path

# Ensure smm/ is importable (mirrors _common.py; harmless if already inserted).
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from _append_impl import now_iso
from _append_impl import resolve_smm_dir as _resolve_smm_dir_impl

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
# Hook I/O
# ---------------------------------------------------------------------------

# _MAX_STDIN_SIZE stays in _common.py: tests patch it there
# (patch.object(_common, "_MAX_STDIN_SIZE", ...)) and read_hook_input below
# looks it up dynamically off the _common module object so the patch takes
# effect.
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


def log_hook_error(reason: str, error_class: str, **ctx: object) -> None:
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
    # Delegates to init.sh when SMM_DIR is unset — without it, cache-derived
    # hook invocations would lose the diagnostic trace. Returns None outside
    # a git repo, in which case the stderr mirror is the only surface.
    smm_dir = _resolve_smm_dir_impl()
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
    import _common

    max_stdin_size = _common._MAX_STDIN_SIZE
    raw = ""
    try:
        raw = sys.stdin.read(max_stdin_size + 1)
        if len(raw) > max_stdin_size:
            log_hook_error(
                f"stdin exceeded {max_stdin_size} bytes",
                error_class="stdin_oversize",
                size=len(raw),
            )
            sys.exit(0)
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        log_hook_error(
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
