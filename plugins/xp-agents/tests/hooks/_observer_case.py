#!/usr/bin/env python3
"""The commit observer's shared harness: a real repo, driven by a plain Bash.

Here rather than in either suite, because `test_commit_observer.py` (what the
observer claims, refuses, and costs) and `test_commit_observer_claims.py` (what
it may NOT claim, and what has to survive for it to claim anything) both drive
the module the same way — through `run_hook` on a NON-commit-shaped command,
which is the only branch the observer is registered on.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import markers
from _commit_repo_case import _RebuildTestCase

ORDINARY_BASH = "ls -la"


class _ObserverCase(_RebuildTestCase):
    def seed_observer(self) -> None:
        self.run_hook(ORDINARY_BASH)

    def observe(self) -> None:
        self.run_hook(ORDINARY_BASH)

    def marker(self) -> dict | None:
        data = markers.marker_read(self.smm_dir, markers.LAST_SEEN_HEAD, "main")
        return data if isinstance(data, dict) else None

    def recorded_hashes(self) -> list[str]:
        return [e["metadata"].get("commit_hash") for e in self.commit_events()]
