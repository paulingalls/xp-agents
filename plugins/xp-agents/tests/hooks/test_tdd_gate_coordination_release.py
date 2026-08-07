#!/usr/bin/env python3
"""The TDD Stop gate's coordination release, and the two fail-opens in it.

Split from test_tdd_gate_session_scope.py, which crossed the 450-line band floor
when these classes landed (a cohesive extraction, not a chronology split: every
test here is about the RELEASE — whether the gate hands a red suite back because
some other agent is active — while the host file is about the WINDOW the signal
is read through).

The release lived in one expression that answered "who am I?" from a source
nothing else used. Both directions below are paired with an over-arming control,
because the dangerous failure here is a gate that never blocks and a gate that
always blocks — and only one of those is visible in a green suite.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import identity
import tdd_check
from _heartbeat_fixtures import coordinate
from _tdd_gate_fixtures import TEAMMATE_CWD, _GateTestCase, filler, session_anchor
from conftest import failing_tests_concern


class TestAbsentAgentIdIsNotASibling(_GateTestCase):
    """The absent-`agent_id` fail-open.

    Having found a failure, the gate asks
    `coordination.has_active_teammates(smm_dir, agent_id)` — "is some OTHER
    agent active?" — and releases if so, because a teammate may own it. It read
    the RAW payload `agent_id`, but the harness sends that field only when a
    hook fires inside a subagent call and Stop fires on the main thread, so the
    value was always `""`. Nothing in coordination equals `""`, so the predicate
    answered yes against ANY entry — and `post_tool_use` writes one under the
    resolved id on every file write, with a 30-minute TTL. The gate that keeps a
    red suite from being abandoned released unconditionally.

    Read the first two tests as a PAIR. The release direction passes today for
    the wrong reason — today it releases for every input — so only the block
    direction fails first, and only together do they say the answer TRACKS
    coordination rather than ignoring it.
    """

    def _coordinate(self, *agent_ids: str) -> None:
        coordinate(self.smm_dir, *agent_ids)

    def test_no_agent_id_and_no_sibling_blocks(self):
        """AC-1. The lead, alone, with its own red suite. `main` IS in
        coordination — the lead writes there itself on every file write, which
        is exactly why comparing against `""` disarmed the gate."""
        self._coordinate("main")
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        self.assertIsNotNone(self._stop(events, dirty=False, agent_id=None))

    def test_no_agent_id_and_a_real_sibling_releases(self):
        """AC-2. Same payload, but a genuine teammate is active, so the failure
        may be its own and the lead must not be held."""
        self._coordinate("main", "worktree-story-007")
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        self.assertIsNone(self._stop(events, dirty=False, agent_id=None))

    def test_the_empty_spelling_matches_the_absent_key(self):
        """Non-vacuity. A missing key and `""` must not diverge — both reach
        `resolve_agent_id`'s falsy branch. Pinning the equality stops a later
        "fix" that special-cases one spelling and leaves the other fail-open."""
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        self._coordinate("main")
        absent = self._stop(events, dirty=False, agent_id=None)
        empty = self._stop(events, dirty=False, agent_id="")
        self.assertIsNotNone(empty)
        self.assertEqual(absent, empty)


class TestOnlyTheLeadMayReleaseOnASibling(_GateTestCase):
    """The second fail-open in the same expression.

    By the time the coordination release is considered, `find_last_test_signal`
    has ALREADY scoped the read: a teammate sees only its OWN signals, the lead
    reads unscoped and legitimately observes everyone's. So "someone else may
    own this failure" can only ever be true for the lead. A teammate reaching
    `signal == "fail"` is looking at a failure `_reader_scope` proved is its
    own, and releasing it because the LEAD has a coordination entry abandons a
    red suite the teammate owns.

    Beyond the story's declared ACs (AC-3 covers only the in-place leg), taken
    here because it is the same defect class — two identity answers inside one
    function — in the same six lines.
    """

    def _coordinate(self, *agent_ids: str) -> None:
        coordinate(self.smm_dir, *agent_ids)

    def test_a_worktree_teammate_is_not_released_by_the_leads_entry(self):
        """`agent_id=None` is payload FIDELITY, not non-vacuity — measured, not
        assumed. Against `_stop`'s default `"main"` this test still fails on the
        pre-fix expression AND on an owner-guard-removed mutant, because with
        `main` excluded the sibling entry still reads as another active agent.
        What popping the key buys is that both resolvers then read the worktree
        name off the cwd, the shape a real Stop payload has (the harness sends
        `agent_id` only inside a subagent call), so the agreement asserted in
        `test_the_two_resolvers_agree_for_a_worktree_teammate` is the one this
        block actually exercises."""
        self._coordinate("main", "worktree-story-003")
        events = [failing_tests_concern(agent_id="worktree-story-003"), *filler(3)]
        result = self._stop(events, cwd=TEAMMATE_CWD, dirty=False, agent_id=None)
        self.assertIsNotNone(result)

    def test_the_lead_is_still_released_by_a_real_sibling(self):
        """Over-arming control. Without it, "never release" satisfies the test
        above while silently deleting the release the gate is meant to have."""
        self._coordinate("main", "worktree-story-003")
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        result = self._stop(events, dirty=False, agent_id=None)
        self.assertIsNone(result)

    def test_the_two_resolvers_agree_for_a_worktree_teammate(self):
        """The one-identity-source claim asserted directly, rather than inferred
        from the block above. `resolve_agent_id` and the reader scope must
        return the SAME name for a worktree teammate on a real payload; the
        original defect was precisely that they could not."""
        payload = {"session_id": "t", "cwd": TEAMMATE_CWD}
        events = [failing_tests_concern(agent_id="worktree-story-003"), *filler(3)]
        self.assertEqual(
            identity.resolve_agent_id(payload),
            tdd_check.reader_scope_owner(events, TEAMMATE_CWD, self.smm_dir),
        )


class TestADeadSiblingDoesNotReleaseTheGate(_GateTestCase):
    """AC-1 through the gate, which is where the criterion is written.

    The predicate is pinned in test_coordination.py; this is the sentence
    itself — "an entry younger than the TTL whose agent is no longer alive
    does not release" — asserted where a lead actually meets it.

    Twenty minutes is chosen so BOTH rows are states a real run reaches: the
    entry is still inside the 30-minute TTL, so the timestamp alone would
    release either way, and only the heartbeat separates the pair. It is the
    window, not the TTL, deciding both answers here.
    """

    SIBLING = "worktree-story-007"
    SESSION = "the-siblings-session"
    #: Inside the entry TTL (30m), outside the heartbeat trust window (15m).
    ENTRY_AGE = 20 * 60

    def _sibling(self, *, beat_age: float) -> None:
        """One teammate entry aged inside the TTL, with a heartbeat of its own."""
        import json
        import time
        from datetime import datetime, timedelta, timezone

        import coordination
        import hook_liveness

        coordination.update_coordination(self.smm_dir, "main", [])
        path = self.smm_dir / ".coordination.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        updated = datetime.now(timezone.utc) - timedelta(seconds=self.ENTRY_AGE)
        data[self.SIBLING] = {
            "working_on": [],
            "updated": updated.isoformat(),
            "session_id": self.SESSION,
        }
        path.write_text(json.dumps(data), encoding="utf-8")
        hook_liveness.write_heartbeat(
            self.smm_dir, session_id=self.SESSION, now=time.time() - beat_age
        )

    def test_a_sibling_whose_session_died_does_not_release(self):
        """The lead is left holding its own red suite, which is its own."""
        self._sibling(beat_age=self.ENTRY_AGE)
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        self.assertIsNotNone(self._stop(events, dirty=False, agent_id=None))

    def test_the_same_sibling_still_releases_while_it_beats(self):
        """Over-arming control: identical entry, live heartbeat. Without it,
        "never release on a sibling" satisfies the test above."""
        self._sibling(beat_age=60)
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        self.assertIsNone(self._stop(events, dirty=False, agent_id=None))


if __name__ == "__main__":
    import unittest

    unittest.main()
