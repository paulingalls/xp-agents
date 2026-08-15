#!/usr/bin/env python3
"""The exclusive, expiring marker claim.

A sibling of `markers.py` rather than a member of it. The claim belongs to the
same marker infrastructure and follows the same symlink-safety rule — a private
`O_EXCL` in each caller would be the third hand-rolled copy of the idiom — but
`markers.py` carries a hard 450-line sub-cap pinned by
`tests/hooks/test_session_markers.py::TestMarkersSplit`, whose instruction on
crossing it is to extract a cohesive group into a sibling module rather than to
record a higher ceiling. This is that group: one operation, one idiom, no
overlap with the read/write/consume family.
"""

import contextlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import markers


def claim(
    smm_dir: Path,
    marker: markers.MarkerDef,
    *,
    ttl_seconds: float,
    agent_id: str = "",
) -> bool:
    """Take `marker` exclusively, or return False if a live claim holds it.

    The CREATE is the claim. `marker_exists` followed by `marker_write` looks
    equivalent and is not: the gap between the two is where four parallel
    firings each read the marker absent and each ran the work it was meant to
    serialise. Atomic writing does not close that gap, because the gap is
    before the write. `O_CREAT | O_EXCL` is the whole mechanism — the same idiom
    `smm/archive.py` uses to claim an archive name rather than assume it.

    `O_NOFOLLOW` refuses a symlinked path outright, matching `marker_exists`,
    which reports a symlinked marker absent. Following it would write through to
    a file we do not own, and expiring it would delete one.

    **The claim EXPIRES, and that is load-bearing rather than tidy-up.** A claim
    held forever silently starves the next legitimate claimant — the same quiet
    failure the claim exists to prevent, arriving from the other side. A holder
    older than `ttl_seconds` is treated as abandoned: unlinked, and the
    exclusive create retried exactly once. Once, not in a loop — two claimants
    expiring the same stale holder must not take turns deleting each other's
    fresh claim.

    Callers pick `ttl_seconds` from how long the work being serialised takes,
    and should bias it SHORT: a duplicate run costs the work twice, while an
    over-long claim costs a skipped run that nothing reports.
    """
    path = markers.marker_path(smm_dir, marker, agent_id)
    if _try_exclusive_create(path):
        return True

    try:
        held_for = time.time() - path.stat().st_mtime
    except OSError:
        # Vanished between the failed create and the stat, or is unreadable.
        # Either way this claimant does not hold it.
        return False
    if held_for <= ttl_seconds:
        return False

    with contextlib.suppress(OSError):
        path.unlink()
    return _try_exclusive_create(path)


def _try_exclusive_create(path: Path) -> bool:
    """Create `path` or report that someone else already has it."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError:
        # FileExistsError for the ordinary contended case; ELOOP for a symlinked
        # path, which is refused rather than followed.
        return False
    with contextlib.suppress(OSError), os.fdopen(fd, "w") as handle:
        handle.write("held\n")
    return True
