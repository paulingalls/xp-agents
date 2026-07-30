#!/usr/bin/env python3
"""How to invoke `scripts/close_common.py` as a subprocess.

The close-pipeline suites are subprocess-based: they run close_common.py as a
script against a hermetic temp git repo, with gh stubbed via a fake script on
PATH (see `_close_fixtures.stub_gh` / `stub_no_gh`) so nothing touches real
GitHub. That invocation is the one thing all three pipeline suites share, so it
lives here rather than being copied into each.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import _branching_fixtures as _bf
from _bases import _PLUGIN_ROOT

_CLOSE_COMMON = _PLUGIN_ROOT / "scripts" / "close_common.py"


def _run(
    args: list[str],
    cwd: str | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Invoke close_common.py with args. Returns CompletedProcess.

    Uses sys.executable so the subprocess works even when env's PATH
    is scoped to a stub dir (gh-absent test setup).
    """
    return subprocess.run(
        [sys.executable, str(_CLOSE_COMMON), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env if env is not None else _bf.GIT_ENV,
    )
