#!/usr/bin/env python3
"""Regression test for the events.jsonl commit-recording write path.

Pins the end-to-end invariant: under brief flock contention short enough
to clear the configured budget, `bash_post_tool.run()` with a valid
git-commit input must record a `commit` event in events.jsonl.

The original failure mode silently dropped commit events when
`_common.bulk_append_safe` swallowed `LockTimeoutError` raised from too
short a flock budget under high parallel-hook contention. This guard
ensures regressions in the write chain become visible at test time.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import bash_post_tool
from _commit_helpers import patch_commits
from _lock_helpers import briefly_held_lock
from conftest import _HookTestCase, _make_bash_input
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_COMMIT


class TestAttributionRegression(_HookTestCase):
    """End-to-end: commit event survives brief flock contention."""

    def test_commit_event_lands_under_lock_contention(self):
        """A commit event must land in events.jsonl despite a brief
        external flock hold of events.lock.

        ``briefly_held_lock`` holds the lock for 0.3 s in a background
        thread and patches ``LOCK_TIMEOUT_SECONDS`` to 2 s, so
        ``bulk_append_safe`` clears contention and lands the commit
        event. The assertion is "budget outlasts hold", not
        "wait the full hold".
        """
        with (
            briefly_held_lock(self.smm_dir),
            patch_commits(
                files=["plugins/xp-agents/scripts/x.py"],
                body="[story-001] regression probe",
                head_sha="abc1234deadbeef",
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

        commit_events = events_of_type(self._read_events(), EVENT_TYPE_COMMIT)
        self.assertEqual(
            len(commit_events),
            1,
            "Commit event should land despite brief lock contention; "
            f"got {len(commit_events)} commit events",
        )


if __name__ == "__main__":
    unittest.main()
