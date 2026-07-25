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

import hook_liveness

HOOK_LIVENESS_PY = Path(__file__).parent.parent / "scripts" / "hook_liveness.py"

_NO_SESSION_ENV = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")


def env(**overrides: str) -> dict[str, str]:
    """A process env with no discoverable session id, plus any overrides."""
    return {**_NO_SESSION_ENV, **overrides}
