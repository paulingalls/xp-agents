#!/usr/bin/env python3
"""Whose failing tests the LEAD's gate is entitled to hold it on.

A worktree teammate already reads scoped — `_reader_scope` gives it an `owner`
and only its OWN signals gate it. The lead reads `owner=None` and observes
every author in the log, including teammates working in a DIFFERENT working
tree. Both directions of that were wrong:

  BLOCKING. The lead was held on a teammate's transient red (concern
  bd245cc42c35, observed live several times during sprint-007). The release it
  was supposed to have — `coordination.has_active_teammates` — is not merely
  stale for these teammates, it never fires: `post_tool_use` is the only writer
  of a coordination entry and it is registered on Write|Edit|MultiEdit only, so
  a teammate that edits through Bash never has an entry to grade.

  RELEASING, and unrecorded. The reverse walk's pass short-circuit had no author
  check either, so a teammate's GREEN run un-gated the lead's own red suite. That
  is the dangerous half — a false block costs a re-run, a false release ships
  broken code — and nothing had reported it.

The discriminator is authorship, not liveness. Attribution answers "is this
failure even about my working tree", which is the question; a liveness backstop
answers "is somebody else running", which releases the lead's own red too.

Split from test_tdd_gate_session_scope.py rather than added to it: that file is
at 385 lines against a 450 band floor, and six rows would carry it across.
test_tdd_gate_in_place_teammate.py came out of the same file for the same
reason.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import identity
from _tdd_gate_fixtures import TEAMMATE_CWD, _GateTestCase, filler, session_anchor
from conftest import failing_tests_concern, passing_tests_status
from identity import extract_worktree_name

_TEAMMATE = extract_worktree_name(TEAMMATE_CWD)
"""The author of TEAMMATE_CWD's events, DERIVED through the same resolver the
gate uses rather than spelled again. That fixture's own docstring names two
hand-written copies of a path a resolver parses as a drift hazard; a
hand-written copy of what it RESOLVES TO is the same hazard one step on."""

_SUBAGENT = "aefef7af4afed4caf"
"""An opaque subagent id, the shape `resolve_agent_id` returns from the raw
payload field inside a subagent call."""


class TestTheLeadIsNotHeldOnAnotherTreesRed(_GateTestCase):
    """The recorded defect. The lead's own red must still hold it, which is
    what separates this from deleting the gate."""

    def test_a_worktree_teammates_red_does_not_hold_the_lead(self):
        """Row 1. No coordination entry for the teammate — the REAL shape of the
        defect, not a TTL-expiry stand-in. A Bash-editing teammate never writes
        one, so the release the gate was supposed to have cannot fire, and
        seeding an entry here would test the release instead of the fix."""
        events = [
            session_anchor(),
            *filler(3),
            failing_tests_concern(agent_id=_TEAMMATE),
        ]
        self.assertIsNone(self._stop(events, dirty=False))

    def test_the_leads_own_red_still_holds_it(self):
        """Row 2, the over-arming control. Without it, a filter that drops
        EVERY author satisfies the row above while deleting the gate."""
        events = [session_anchor(), *filler(3), failing_tests_concern()]
        self.assertIsNotNone(self._stop(events, dirty=False))

    def test_an_in_place_teammate_authors_as_the_lead(self):
        """Row 3, and it is an AUTHORSHIP pin rather than a gate row — because
        at the gate there is nothing left to distinguish.

        `spawn_teammate --in-place` runs in the MAIN checkout, so its red suite
        IS the lead's and must still gate. It does, for a reason that needs no
        code: `resolve_agent_id` falls back to `resolve_agent_id_from_cwd`, and a
        cwd with no `worktree-` segment answers `main`. Its events are therefore
        authored exactly like the lead's own, the prefix test never considers
        them, and row 2 already covers the gate behaviour.

        Pinned HERE because the whole "in-place needs no exemption" argument
        rests on it, and because a row that authored under the teammate's NAME
        instead would pin a state production cannot produce.
        """
        self.assertEqual(identity.resolve_agent_id({"cwd": "/repo/main"}), "main")
        self.assertFalse(identity.is_teammate_agent_id("main"))

    def test_a_null_author_does_not_crash_the_gate(self):
        """An event may carry `agent_id` present-and-NULL, and `.get(k, "")`
        returns None for that shape rather than the default — the same trap that
        took the whole post-Bash hook down through `cwd` one release ago. Here it
        would raise AttributeError out of a Stop gate.

        Reads as "not another tree's", so the signal still gates: an author we
        cannot identify is not one we can prove is elsewhere.
        """
        concern = failing_tests_concern()
        concern["agent_id"] = None
        events = [session_anchor(), *filler(3), concern]
        self.assertIsNotNone(self._stop(events, dirty=False))

    def test_an_opaque_subagent_id_still_holds_the_lead(self):
        """Row 4. A subagent runs in its parent's working tree, so its red is
        the parent's problem. This is the row that makes the predicate "names a
        worktree teammate" rather than "is not me": the latter would drop this
        author and lose the lead's real failures.

        It also pins the known residual — a WORKTREE teammate's subagent
        authors under an id of this same shape, so the false block survives that
        one path. Preserved deliberately; the alternative is worse.
        """
        events = [
            session_anchor(),
            *filler(3),
            failing_tests_concern(agent_id=_SUBAGENT),
        ]
        self.assertIsNotNone(self._stop(events, dirty=False))


class TestAnotherTreesGreenDoesNotClearTheLead(_GateTestCase):
    """The fail-open half. The walk returns on the first pass-shaped status it
    meets, and for the lead that status could be anyone's."""

    def test_a_worktree_teammates_green_does_not_clear_the_leads_red(self):
        """Row 5. The teammate's pass is NEWER, so the reverse walk reaches it
        first and short-circuits before the lead's own unresolved failure. The
        lead then stops with a red suite and no gate fired."""
        events = [
            session_anchor(),
            *filler(1),
            failing_tests_concern(),
            passing_tests_status(agent_id=_TEAMMATE),
            *filler(2),
        ]
        self.assertIsNotNone(self._stop(events, dirty=False))

    def test_the_leads_own_green_still_clears_its_red(self):
        """Row 6, the control. The short-circuit must survive for its real
        owner — a later green run of one's OWN suite does un-gate an earlier
        failure, and that is the mechanism, not a bug."""
        events = [
            session_anchor(),
            *filler(1),
            failing_tests_concern(),
            passing_tests_status(),
            *filler(2),
        ]
        self.assertIsNone(self._stop(events, dirty=False))


if __name__ == "__main__":
    import unittest

    unittest.main()
