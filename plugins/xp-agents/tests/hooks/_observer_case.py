#!/usr/bin/env python3
"""The commit observer's shared harness: a real repo, driven by a plain Bash.

Here rather than in any one suite, because four of them drive the module the
same way — through `run_hook` on a NON-commit-shaped command, which is the only
branch the observer is registered on. `test_commit_observer.py` pins what the
observer claims, refuses, and costs; `test_commit_observer_claims.py` pins what
it may NOT claim; `test_commit_observer_cycle.py` pins what a recorded commit
does to the review records and what an unrecorded one must not;
`test_commit_event_recording.py` pins one fixture per commit shape that reached
HEAD without reaching the log. A per-file copy of this class is how a fix to the
seeding shape reaches one suite and not the others.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import markers
from _commit_repo_case import _RebuildTestCase
from conftest import make_event
from event_schema import EVENT_TYPE_COMMIT

# An ordinary Bash that is not commit-shaped and not a test run — the shape of
# the overwhelming majority of tool calls, and the one the catch-up observation
# has to ride on. `ls` rather than anything git: the observer must not need a
# git-shaped command to notice that HEAD moved.
ORDINARY_BASH = "ls -la"


class _ObserverCase(_RebuildTestCase):
    """A repo whose session has already had one ordinary Bash.

    Every case needs that, because the FIRST observation of a session has no
    last-seen HEAD to compare against and must seed rather than reconcile — an
    unbounded lower bound would walk the whole history. Making the seeding Bash
    explicit in each test keeps that cold start visible rather than hiding it
    in setUp.
    """

    def seed_observer(self) -> str | None:
        """The first Bash of a session: seeds the marker, reconciles nothing."""
        return self.run_hook(ORDINARY_BASH)

    def observe(self) -> str | None:
        """A later ordinary Bash — where the catch-up happens."""
        return self.run_hook(ORDINARY_BASH)

    def marker(self) -> dict | None:
        data = markers.marker_read(self.smm_dir, markers.LAST_SEEN_HEAD, "main")
        return data if isinstance(data, dict) else None

    def recorded_hashes(self) -> list[str]:
        return [e["metadata"].get("commit_hash") for e in self.commit_events()]

    def reword_rebase(self, base: str, message: str) -> None:
        """A reword-rebase: `base` survives untouched, everything after it is
        rewritten to new hashes carrying the same trailers.

        Here rather than in one suite because two of them need the same
        specimen — one asserts what is NOT recorded from it, the other what the
        decline still owes. A real `git rebase`, never `git commit --amend`:
        amend rewrites the same way but sets no ORIG_HEAD and writes no
        `rebase` reflog entry, so it exercises neither signal and would pass
        against a module that detects nothing.
        """
        msg_file = self.repo / ".rebase-message"
        msg_file.write_text(message)
        self.git("rebase", "--no-ff", base, "-x", f"git commit --amend -F {msg_file}")
        msg_file.unlink()

    def record_commit_event(self, commit_hash: str) -> None:
        """Pretend a commit already reached the log, as the branch point has."""
        _common.append_safe(
            self.smm_dir,
            make_event(
                EVENT_TYPE_COMMIT,
                content="already accounted for",
                metadata={"commit_hash": commit_hash, "action": "commit_success"},
            ),
        )
