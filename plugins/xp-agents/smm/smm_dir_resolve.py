#!/usr/bin/env python3
"""SMM directory resolution.

Moved out of ``_append_impl.py`` to keep that file under the line-count cap.
Re-exported from ``_append_impl`` BY IDENTITY (``from smm_dir_resolve import
now_iso, resolve_smm_dir, _derive_smm_dir``) so every existing
``from _append_impl import resolve_smm_dir`` / ``_append_impl.resolve_smm_dir``
reference — and every ``mock.patch`` site targeting it — resolves unchanged.
"""

import os
import subprocess
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
