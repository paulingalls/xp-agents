#!/usr/bin/env python3
"""Throwaway spike recorder: capture a hook payload VERBATIM.

Registered for every event in `hooks/hooks.codex.json` so story-003 can read
real payloads instead of inferring them from documentation.

Three properties are load-bearing, and each exists because its opposite would
corrupt the observation rather than merely inconvenience it:

1. **Verbatim bytes.** stdin is read and written as bytes, never decoded and
   re-encoded, so key order, escaping, whitespace and invalid UTF-8 all survive.
   A `json.loads`/`json.dumps` round-trip would silently normalise the very
   shape the spike exists to record.
2. **Each payload in its own file.** Newline-delimited output would corrupt if a
   host ever pretty-printed a payload; a separate file per firing cannot.
3. **Never stdout, always exit 0.** Stdout from a hook is injected context, and
   a non-zero exit can block the host's turn. This recorder observes; it must
   not participate. A write it cannot make is reported on STDERR instead, so a
   denied write stays distinguishable from an event that never fired.

Destination: `$XP_SPIKE_DIR`, else a stable temp directory. Never the real
`events.jsonl` — spike traffic in the shared event log is not recoverable.
"""

import contextlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_ENV_KEYS = ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT", "PLUGIN_DATA", "CLAUDE_PLUGIN_DATA")

_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")


def _spike_dir() -> Path:
    override = os.environ.get("XP_SPIKE_DIR")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "xp-codex-spike"


def _report_write_failure(what: str, exc: BaseException) -> None:
    """Say on STDERR that a record could not be written, and carry on.

    Stderr and not stdout, exit status still 0: nothing in this rig may inject
    context or block the host's turn. But a swallowed write leaves the output
    directory looking exactly like a hook that never fired, and that is the one
    observation this milestone must never produce by accident. An out-of-band
    canary cannot settle it either — a hook process need not run under the same
    sandbox policy as the shell that ran the canary, so "the dir was writable
    from my shell" is not evidence that the hook could write it.

    Shared by both probes, which import this module already.
    """
    with contextlib.suppress(Exception):
        print(
            f"xp-spike: could not write {what}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def _event_name(raw: bytes) -> str:
    """Best-effort event name for the filename only — never touches *raw*.

    Unparseable stdin is a finding worth keeping, not a reason to drop the
    payload, so this degrades to "unknown" and the bytes are still written.
    """
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(parsed, dict):
        return "unknown"
    name = parsed.get("hook_event_name")
    if not isinstance(name, str) or not name:
        return "unknown"
    return "".join(ch if ch in _SAFE else "_" for ch in name)[:60]


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""

    event = _event_name(raw)
    # time_ns + pid keeps concurrent firings from colliding without a lock,
    # and sorts chronologically so story-003 can read the sequence.
    stem = f"{time.time_ns():024d}-{os.getpid()}-{event}"

    try:
        root = _spike_dir()
        (root / "payloads").mkdir(parents=True, exist_ok=True)
        payload_file = root / "payloads" / f"{stem}.raw"
        payload_file.write_bytes(raw)

        entry = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "hook_event_name": event,
            "payload_file": payload_file.name,
            "stdin_bytes": len(raw),
            "cwd": os.getcwd(),
            "env": {k: os.environ.get(k) for k in _ENV_KEYS},
        }
        with (root / "index.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        # A recorder that fails loudly would block the host mid-observation, so
        # the exit status stays 0 — but the failure is stated on stderr, because
        # an absent payload file on its own is NOT a signal: it reads the same
        # as an event that never fired.
        _report_write_failure(f"payload for {event}", exc)

    return 0


if __name__ == "__main__":
    sys.exit(main())
