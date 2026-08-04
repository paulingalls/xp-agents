#!/usr/bin/env python3
"""Throwaway spike probe: what bounds a blocking Stop on this harness?

All four shipped Stop gates release on one field, and the compatibility table
called it "no known analogue" for Codex. It turned out to be PRESENT, on both
Stop and SubagentStop, reading False. Presence is not release: a gate that only
lets go when the field is True is *worse off* with a matching field name that
never flips than with no field at all, because a port reads the name as
compatible. So this probe asks the only question that matters — does it ever
flip? — by actually blocking and watching.

Blocking a Stop is the one thing in this rig that could run away: an unbounded
block means the model never gets to end its turn. Every branch below therefore
fails SAFE, meaning non-blocking:

- A counter it cannot read is treated as AT the cap, never as zero. Zero would
  restart the count on every firing and assemble an unbounded loop out of
  individually-bounded decisions — and an unreadable counter is precisely the
  state a sandbox-denied write leaves behind.
- A counter it cannot write is treated as at the cap too, because a probe that
  blocks without recording that it blocked can never reach its cap.

The cap is a safety property, not a convenience, and `test_stop_probe.py` pins
all three legs.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _dump_payload

# Deliberately small. Three firings is enough to see whether the release field
# flips, and few enough that a runaway would be cheap even if every guard failed.
CAP = 3

_COUNTER_NAME = "stop_block_count"
_LOG_NAME = "stop_firings.jsonl"


def _read_count(counter: Path) -> int:
    """Blocks used so far, or CAP when unknowable — never a permissive default.

    Absent and unreadable are separated deliberately, and the distinction is the
    whole bound:

    - **Absent** is the first firing. Nothing has blocked yet, so 0 is the true
      count. Treating it as CAP would make the probe never block and answer AC-3
      with a non-observation.
    - **Present but unparseable, or unreadable** is a count we cannot trust. CAP,
      because reading it as 0 would restart the count on every firing and
      assemble an unbounded loop out of individually-bounded decisions.
    """
    if not counter.exists():
        return 0
    try:
        return int(counter.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return CAP


def _record(root: Path, payload: dict, blocked: bool, count: int) -> None:
    entry = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "hook_event_name": payload.get("hook_event_name"),
        "session_id": payload.get("session_id"),
        # Absent and False are DIFFERENT findings: False means the host sends the
        # field and has not set it; absent means there is no release channel at
        # all. Collapsing them would answer AC-3 with the wrong shape.
        "stop_hook_active": payload.get("stop_hook_active"),
        "stop_hook_active_present": "stop_hook_active" in payload,
        "blocked": blocked,
        "blocks_used": count,
        "pid": os.getpid(),
    }
    with (root / _LOG_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}

    root = _dump_payload._spike_dir()
    counter = root / _COUNTER_NAME
    count = _read_count(counter)

    blocked = False
    if count < CAP:
        # Persist BEFORE blocking. If the write fails we must not block, or the
        # cap becomes unreachable and the bound is gone.
        try:
            root.mkdir(parents=True, exist_ok=True)
            counter.write_text(str(count + 1), encoding="utf-8")
            blocked = True
        except OSError as exc:
            _dump_payload._report_write_failure("stop block counter", exc)

    try:
        root.mkdir(parents=True, exist_ok=True)
        _record(root, payload, blocked, count)
    except OSError as exc:
        _dump_payload._report_write_failure("stop firing record", exc)

    if blocked:
        sys.stdout.write(
            json.dumps(
                {
                    "decision": "block",
                    "reason": (
                        f"xp-spike: bounded Stop-loop probe, block {count + 1} of "
                        f"{CAP}. Reply with the single word CONTINUE and nothing "
                        "else, then stop."
                    ),
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
