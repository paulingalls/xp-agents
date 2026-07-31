#!/usr/bin/env python3
"""Which paths are the user's REAL SMM data roots — the litter guard.

Shared by the two init suites that assert a derivation never lands in one.
Extracted from `test_init.py` when it was split at 724 lines; both halves need
it and neither owns it.
"""

from pathlib import Path

# Every root a stray derivation could land in for real. A TUPLE, not one path:
# `~/.xp-agents/data` became the default root, so a guard that knew only the
# plugin-data root would silently stop catching litter — the failure mode being
# that the guards keep passing while the suite writes to a live SMM.
_REAL_DATA_ROOTS = (
    Path.home() / ".claude" / "plugins" / "data" / "xp-agents-xp-agents",
    Path.home() / ".claude" / "plugins" / "data" / "xp-agents-inline",
    Path.home() / ".xp-agents" / "data",
)


def _is_real_root(path: str | Path | None) -> bool:
    """True if path is one of the real data roots or lives under one."""
    if not path:
        return False
    p = Path(path)
    return any(p == root or root in p.parents for root in _REAL_DATA_ROOTS)
