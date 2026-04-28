#!/usr/bin/env python3
"""Regression test for the events.jsonl commit-recording write path.

Pins the end-to-end invariant: under brief flock contention short enough
to clear a sane budget, `bash_post_tool.run()` with a valid git-commit
input must record a `commit` event in events.jsonl.

The original failure mode silently dropped commit events when
`_common.bulk_append_safe` swallowed `LockTimeoutError` raised from a
2 s flock budget under high parallel-hook contention. This guard
ensures regressions in the write chain become visible at test time.
"""

import fcntl
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import bash_post_tool
from conftest import _HookTestCase, _make_bash_input


class TestAttributionRegression(_HookTestCase):
    """End-to-end: commit event survives brief flock contention."""

    @unittest.expectedFailure
    def test_commit_event_lands_under_lock_contention(self):
        """A commit event must land in events.jsonl despite a brief
        external flock hold of events.lock.

        Holds the lock for ~3 seconds in a background thread (longer
        than the 2 s flock budget) and invokes `bash_post_tool.run()`
        with a valid git-commit input. Currently fails because
        `bulk_append_safe` suppresses LockTimeoutError and the commit
        event is dropped silently.
        """
        lock_file = self.smm_dir / "events.lock"
        lock_acquired = threading.Event()
        release_lock = threading.Event()

        def hold_lock() -> None:
            with open(lock_file, "a") as fd:
                fcntl.flock(fd, fcntl.LOCK_EX)
                lock_acquired.set()
                # Held window must outlast the flock acquisition budget
                # under test, but clear well before the test runner's
                # join() timeout below.
                release_lock.wait(timeout=3.0)
                fcntl.flock(fd, fcntl.LOCK_UN)

        holder = threading.Thread(target=hold_lock)
        # Register cleanup before start() so a flock-acquire failure on
        # the holder still gets the thread joined and signaled.
        self.addCleanup(holder.join, 5.0)
        self.addCleanup(release_lock.set)
        holder.start()
        self.assertTrue(
            lock_acquired.wait(timeout=2.0),
            "holder thread failed to acquire events.lock",
        )

        with (
            patch(
                "commits.get_committed_files",
                return_value=["plugins/xp-agents/scripts/x.py"],
            ),
            patch(
                "commits.get_commit_message_body",
                return_value="[story-001] regression probe",
            ),
            patch(
                "commits.get_head_commit_hash",
                return_value="abc1234deadbeef",
            ),
        ):
            # cwd is the git-repo root in production; here it is just a
            # neutral path because every git-side call is mocked above.
            # Matches the _make_bash_input default to avoid implying that
            # the SMM dir doubles as a working tree.
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m '[story-001] regression probe'",
                    stdout=(
                        "[main abc1234] [story-001] regression probe\n 1 file changed"
                    ),
                ),
                smm_dir=self.smm_dir,
            )

        commit_events = [e for e in self._read_events() if e.get("type") == "commit"]
        self.assertEqual(
            len(commit_events),
            1,
            "Commit event should land despite brief lock contention; "
            f"got {len(commit_events)} commit events",
        )


if __name__ == "__main__":
    unittest.main()
