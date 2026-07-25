#!/usr/bin/env python3
"""Hook-liveness heartbeat: the marker a running hook leaves behind.

When the hook runtime fails to load, every gate it enforces disappears and
the session looks normal. The check that would say so has nowhere to run —
it would itself be a hook. A marker that could only have been written BY a
hook, read by an instruction-time preload, breaks that circle: the preload
still executes when the thing it tests is broken.

This module is the primitive only — the write helper, the session-id
candidate chain, the staleness predicate, and a thin CLI. The hooks that
refresh the marker and the preload that consumes the verdict live
elsewhere.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import markers

# ---------------------------------------------------------------------------
# Verdict codes
# ---------------------------------------------------------------------------

CODE_LIVE = "live"
CODE_NO_MARKER = "no-marker"


@dataclass(frozen=True, slots=True)
class Liveness:
    """A liveness verdict plus the sentence a caller should print.

    `code` is the stable machine token callers branch on; `reason` is prose
    for a human. Callers must never branch on `reason` — its wording is
    free to change.
    """

    live: bool
    reason: str
    code: str


_NOT_LOADED = (
    "The hook runtime is not running: the plugin providing it is likely "
    "not loaded, disabled, or registered under a path that no longer exists."
)


# ---------------------------------------------------------------------------
# Predicate
# ---------------------------------------------------------------------------


def check_liveness(smm_dir: Path) -> Liveness:
    """Report whether the hook runtime is live for the calling session."""
    data = markers.marker_read(smm_dir, markers.HOOK_HEARTBEAT)
    if data is None:
        return Liveness(
            False,
            f"No hook-liveness heartbeat has been recorded. {_NOT_LOADED}",
            CODE_NO_MARKER,
        )
    return Liveness(True, "Hook runtime is live.", CODE_LIVE)
