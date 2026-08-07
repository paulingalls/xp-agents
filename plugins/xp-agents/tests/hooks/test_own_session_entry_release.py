#!/usr/bin/env python3
"""An entry written inside OUR session never releases a Stop gate.

One session holds several agent ids. A non-xp subagent — a general-purpose
helper, or whatever the host calls its generic delegate — runs the same
PostToolUse hook the lead does, resolves its own agent id, and writes its own
coordination entry under our session id. The gates then read that entry as
"a sibling may own this failure" and hand back a red suite nobody else owns.

Reading an own-session entry as UNDETERMINED bounded that window at the entry
TTL but did not close it: undetermined falls back to the timestamp, so for the
whole TTL one file write by one subagent still released the lead. The verdict
here is structural, not another threshold — an own-session entry is a definite
not-a-teammate, so no number decides it.

Why no real teammate is hidden by that: the spawn builds ONE child environment
with every session-id candidate popped, and uses it for both the worktree and
the in-place shape. A teammate therefore records its own id or None, never
ours, so nothing reachable through this branch is a sibling.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _heartbeat_fixtures import env as _env
from test_coordination import _LivenessTestCase


class _OwnSessionTestCase(_LivenessTestCase):
    """Fixtures for the own-session verdict.

    Reuses the liveness fixtures rather than restating them: the entry ages,
    the heartbeat planting and the FRESH/AGED pair are the same ones the
    predicate's other rows are written against, and a second copy of them
    would be free to drift away from the behaviour under test.
    """

    #: The session the lead is running in — the one the assertions read as ours.
    OURS = "the-leads-own-session"
    #: An agent id belonging to a non-xp subagent of ours, not to any sibling.
    OUR_SUBAGENT = "subagent-42"

    def _our_subagents_entry(self, *, age: float) -> None:
        """One entry our own subagent left behind, with our heartbeat beating.

        Both halves matter. The entry carries OUR session id because the
        subagent inherited our environment; our heartbeat is fresh because we
        are the ones still working — which is exactly why our own liveness
        says nothing about whether that agent id still exists.
        """
        self._entry(self.OUR_SUBAGENT, age=age, session_id=self.OURS)
        self._beat(self.OURS, age=self.FRESH)

    def _as_us(self, call):
        """Run *call* with the lead's session id exposed to the resolver."""
        with patch.dict(os.environ, _env(CLAUDE_CODE_SESSION_ID=self.OURS)):
            return call()


class TestOurOwnSubagentIsNotASibling(_OwnSessionTestCase):
    """AC-1 through AC-3 at the predicate."""

    def test_our_own_subagents_fresh_entry_is_not_an_active_teammate(self):
        """AC-1. Inside the TTL, which is the whole defect: the timestamp is
        recent because the subagent really did write a file moments ago, and
        that write is ours, not a sibling's."""
        self._our_subagents_entry(age=self.FRESH)
        self.assertFalse(self._as_us(self._active))

    def test_a_teammate_recording_no_session_id_is_unchanged(self):
        """AC-2. The shape a teammate on a host that exposes no id records.
        The verdict must not reach it: undetermined still falls back to the
        TTL, so a fresh entry is still active and an aged one still is not."""
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=None)
        self.assertTrue(self._as_us(self._active))

    def test_a_teammate_recording_its_own_session_id_is_unchanged(self):
        """AC-2, the other teammate shape: its own id, its own heartbeat."""
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertTrue(self._as_us(self._active))

    def test_another_sessions_fresh_heartbeat_still_counts_when_aged(self):
        """AC-3. The liveness leg survives the new verdict: an entry from
        ANOTHER session is read through its heartbeat, not through ours, so an
        aged entry with a beating session is still an active teammate."""
        self._entry(self.TEAMMATE, age=self.AGED, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertTrue(self._as_us(self._active))

    def test_a_real_sibling_still_counts_beside_our_own_subagent(self):
        """Over-arming control. "Skip our own session" must skip only the
        entries our session wrote — with a live teammate also present, the
        answer is still yes."""
        self._our_subagents_entry(age=self.FRESH)
        self._entry(self.TEAMMATE, age=self.FRESH, session_id=self.SESSION)
        self._beat(self.SESSION, age=self.FRESH)
        self.assertTrue(self._as_us(self._active))


if __name__ == "__main__":
    unittest.main()
