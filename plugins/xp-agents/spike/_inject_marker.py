#!/usr/bin/env python3
"""Throwaway spike probe: does injected context actually reach the model?

The measurement only means something if the marker could have reached the model
by NO other route. Plan review caught the first draft failing exactly there: the
outer prompt carried the marker string, so the model would echo it whether or
not anything was injected — a check that passes against an inert injector, which
measures nothing.

So the marker is MINTED HERE, per invocation, from `uuid4`:

- **Not read from the environment.** An env-supplied marker is one the outer
  runner could plant and the prompt could carry, reopening the hole above.
- **Fresh every firing.** A stale or predictable value could arrive from an
  earlier run, a cached transcript, or a guess.
- **Recorded locally.** The outer run compares the model's output against this
  record; without it, "the marker appeared" is an unverifiable claim.

The paired control run — this handler UNWIRED, same prompt — must produce no
marker at all. That is what makes a positive result falsifiable.

`hookEventName` echoes the payload rather than being hardcoded, so the same
instrument serves a later story that asks the same question at a different
point in the lifecycle.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import _dump_payload

# Labelled so the model can find and report it without the prompt naming the
# value. The prompt asks "report whatever marker you were handed"; the label is
# the handle, the uuid is the evidence.
_LABEL = "XP-SPIKE-MARKER"

_DEFAULT_EVENT = "SessionStart"


def _event_name(raw: bytes) -> str:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _DEFAULT_EVENT
    if not isinstance(parsed, dict):
        return _DEFAULT_EVENT
    name = parsed.get("hook_event_name")
    return name if isinstance(name, str) and name else _DEFAULT_EVENT


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""

    # uuid4, never os.environ: see the module docstring. This line is the whole
    # reason the AC-3 result is falsifiable.
    marker = f"{_LABEL}-{uuid.uuid4().hex}"
    event = _event_name(raw)

    try:
        root = _dump_payload._spike_dir()
        root.mkdir(parents=True, exist_ok=True)
        entry = {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "marker": marker,
            "hook_event_name": event,
            "pid": os.getpid(),
        }
        with (root / "injected_markers.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        # Deliberate: if the record cannot be written, still inject. A run whose
        # marker was injected but not recorded is inconclusive, which the outer
        # runner detects by finding no record — whereas refusing to inject would
        # turn a write problem into a false negative on the AC.
        pass

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": (
                        f"{marker}\n"
                        "The line above is a one-time marker handed to you by "
                        "the session. If you are asked which marker you were "
                        "given, report it verbatim."
                    ),
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
