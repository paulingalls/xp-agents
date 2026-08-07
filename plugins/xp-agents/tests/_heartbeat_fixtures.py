#!/usr/bin/env python3
"""Shared env fixtures for whose SESSION a piece of test code runs as.

Every session-id candidate is pinned to "", which the resolution chain
reads as absent. Tests opt back in by overriding one. Without this, a
developer running the suite from inside a live harness inherits a real
session id and the per-session marker under test moves.

`as_session` is the other half of the same idea, for the writers. Anything a
test writes by calling production code is stamped with the session the SUITE
runs as, so a test that plants "another agent's" artifact by calling that code
directly plants it under OUR id — and a reader that tells own-session artifacts
apart from a stranger's then reads the plant as its own. Wrap the write to give
it the provenance the test means it to have.
"""

import contextlib
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

import hook_liveness
import markers

HOOK_LIVENESS_PY = Path(__file__).parent.parent / "scripts" / "hook_liveness.py"

_NO_SESSION_ENV = dict.fromkeys(hook_liveness.SESSION_ID_ENV_CANDIDATES, "")


def env(**overrides: str) -> dict[str, str]:
    """A process env with no discoverable session id, plus any overrides."""
    return {**_NO_SESSION_ENV, **overrides}


@contextlib.contextmanager
def as_session(session_id: str) -> Iterator[None]:
    """Run the block as a process that belongs to *session_id*.

    Blanking the rest is the load-bearing half, not which candidate carries
    the id: the chain REFUSES when two hold different values, so setting one
    on top of the suite-wide pin without `env`'s blanks would resolve to None
    and the block would run as nobody. With the blanks in place any single
    candidate resolves; the top one is used because that is where this suite
    pins containment (see `_env_hygiene`), and it is read off the chain rather
    than named so a new host variable cannot leave the fixture setting a
    candidate that no longer wins.
    """
    with patch.dict(
        os.environ, env(**{hook_liveness.SESSION_ID_ENV_CANDIDATES[0]: session_id})
    ):
        yield


def coordinate(
    smm_dir: Path, *agent_ids: str, working_on: list[str] | None = None
) -> None:
    """Plant one coordination entry per agent id, each written as ITS OWN process.

    The session stamp is provenance, and `has_active_teammates` reads it: an
    entry carrying the READER's session id belongs to a subagent of the reader
    rather than to a sibling, so it neither releases nor defers anything.
    Calling the writer bare stamps every entry with the id the suite runs as,
    which would make each "other agent" planted here indistinguishable from the
    reader's own subagent — a state no real teammate can be in, because the
    spawn strips every session-id candidate from the one environment both
    teammate shapes are launched with.

    `main` is written as its own session too. These fixtures plant it for the
    readers that are TEAMMATES, and to a teammate the lead is another session;
    where the reader is the lead instead, its own key is dropped before the
    stamp is ever consulted.
    """
    import coordination

    for aid in agent_ids:
        with as_session(f"the-session-of-{aid}"):
            coordination.update_coordination(smm_dir, aid, working_on or [])


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
