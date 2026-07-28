#!/usr/bin/env python3
"""Shared env fixture for the hook-liveness heartbeat suites.

Every session-id candidate is pinned to "", which the resolution chain
reads as absent. Tests opt back in by overriding one. Without this, a
developer running the suite from inside a live harness inherits a real
session id and the per-session marker under test moves.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import hook_liveness
import markers

HOOK_LIVENESS_PY = Path(__file__).parent.parent / "scripts" / "hook_liveness.py"

_NO_SESSION_ENV = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")


def env(**overrides: str) -> dict[str, str]:
    """A process env with no discoverable session id, plus any overrides."""
    return {**_NO_SESSION_ENV, **overrides}


def heartbeat_payload(smm_dir: Path, session_id: str) -> dict | None:
    """Read a session's heartbeat marker as its json payload, or None.

    `marker_read` is typed `str | dict | None` because its return follows
    `MarkerDef.content_type`, which a static reader cannot resolve per call
    site. Heartbeat markers are json-typed, so the `str` leg is unreachable
    here — but silently coercing it to None would hide the day someone
    re-types the marker. Narrow loudly instead, in one place both heartbeat
    suites share.
    """
    payload = markers.marker_read(smm_dir, hook_liveness.heartbeat_marker(session_id))
    if payload is None or isinstance(payload, dict):
        return payload
    raise AssertionError(
        f"heartbeat marker read as text, expected a json payload: {payload!r}"
    )
