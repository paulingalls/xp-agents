#!/usr/bin/env python3
"""An own-session coordination entry releases neither Stop gate — as subprocesses.

story-003 pinned this verdict in-process, at the predicate and at both gates
(`tests/hooks/test_own_session_entry_release.py`). Those rows inject the
reader's session id with `as_session`, which patches `os.environ` inside the
running interpreter. What they cannot reach is the boundary the verdict actually
turns on: the gate resolves its session id from a REAL process environment, and
the entry it compares against was stamped by a different process. Writer and
reader agreeing across that boundary is the same asymmetry discovery
`d49c2d1fb85b` is about, one layer up from the heartbeat.

So this drives both consumers of `coordination.has_active_teammates` —
`tdd_stop_gate.py` and `sprint_stop_gate.py` — the way the platform drives them:
own process, JSON on stdin, session id in the environment.

Each gate gets an over-arming control: a REAL sibling's entry, identical
staging, must still release. Without it, a gate that blocked unconditionally
would satisfy every row here.

The entry itself is planted in-process. That is setup, not the subject — the
entry is a JSON file, and which process wrote it matters only in that it carries
a session stamp, which `as_session` sets exactly as a real writer would.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import coordination
import hook_liveness
from _heartbeat_fixtures import as_session
from _heartbeat_fixtures import env as _no_id_env
from _tdd_gate_fixtures import filler, session_anchor
from conftest import (
    SPRINT_IN_PROGRESS,
    _IntegrationTestCase,
    _make_stop_input,
    failing_tests_concern,
)


class _OwnSessionGateE2ECase(_IntegrationTestCase):
    """Both gates, run as their own processes, in one named session."""

    #: The session the lead is running in — what the gate must read as "ours".
    OURS = "the-leads-own-session"
    #: An agent id belonging to a non-xp subagent of ours, not to any sibling.
    OUR_SUBAGENT = "subagent-42"
    #: A genuine teammate: its own agent id AND its own session.
    SIBLING_AGENT = "worktree-story-999"
    SIBLING_SESSION = "the-session-of-a-real-teammate"

    def _entry(self, agent_id: str, session_id: str) -> None:
        """Plant one coordination entry stamped with *session_id*.

        Not `_heartbeat_fixtures.coordinate`, which hardcodes the stamp to
        `the-session-of-<agent id>` — that shape cannot express the case under
        test, an entry carrying OUR id under someone else's agent id.
        """
        with as_session(session_id):
            coordination.update_coordination(self.smm_dir, agent_id, [])

    def _our_subagents_entry(self) -> None:
        """The defect's shape: our own subagent's entry, our heartbeat beating.

        Both halves matter. The entry carries our session id because the
        subagent inherited our environment; our heartbeat is fresh because we
        are the one still working — which is precisely why our own liveness says
        nothing about whether that agent id still exists.
        """
        self._entry(self.OUR_SUBAGENT, self.OURS)
        hook_liveness.write_heartbeat(self.smm_dir, session_id=self.OURS)

    def _a_real_siblings_entry(self) -> None:
        """The control: another session's entry, and that session is alive."""
        self._entry(self.SIBLING_AGENT, self.SIBLING_SESSION)
        hook_liveness.write_heartbeat(self.smm_dir, session_id=self.SIBLING_SESSION)

    def _our_env(self) -> dict:
        """A process environment that belongs to `OURS`, and to nothing else.

        The blanks are load-bearing for the same reason `as_session` blanks —
        an id that disagrees with the suite-wide pin resolves to None, and the
        gate would then run as nobody, reaching the TTL fallback rather than the
        own-session skip.
        """
        return _no_id_env(**{hook_liveness.SESSION_ID_ENV_CANDIDATES[0]: self.OURS})

    def _stop(self, script: str) -> dict | None:
        """Run a Stop gate as its own process; return its decision, or None.

        `agent_id` is dropped rather than set, for the reason spelled out in
        `_tdd_gate_fixtures._run_gate`: a real Stop payload has no such key.
        """
        payload = _make_stop_input(session_id=self.OURS)
        payload.pop("agent_id", None)
        result = self._run_script_with_env(script, payload, self._our_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return None
        return json.loads(result.stdout)


class TestTheTddGateHoldsARedSuiteOfItsOwn(_OwnSessionGateE2ECase):
    """`tdd_stop_gate.py`, driven as the platform drives it."""

    def _seed_red(self) -> None:
        """A red suite the lead reads UNSCOPED, which is the only reader that
        can reach the release — see `tdd_stop_gate`'s `reader_scope_owner`
        branch. Same event shape story-003 uses at the gate."""
        self._seed_events([session_anchor(), *filler(3), failing_tests_concern()])

    def test_our_own_subagents_entry_does_not_release_the_gate(self):
        self._seed_red()
        self._our_subagents_entry()
        decision = self._stop("tdd_stop_gate.py")
        self.assertIsNotNone(decision, "the lead was released on an entry of its own")
        assert decision is not None
        self.assertEqual(decision["decision"], "block")

    def test_the_block_names_the_tests_and_not_a_sibling(self):
        """AC#3's second half. A gate that blocked with a reason about teammates
        would be describing a state it just decided was not the case."""
        self._seed_red()
        self._our_subagents_entry()
        decision = self._stop("tdd_stop_gate.py")
        assert decision is not None
        reason = decision["reason"]
        self.assertIn("failing tests", reason.lower())
        for absent in ("teammate", "sibling"):
            self.assertNotIn(absent, reason.lower(), reason)

    def test_a_real_sibling_still_releases_the_same_red_suite(self):
        """Over-arming control. Identical suite, identical staging, an entry
        from a live other session — and the lead must still be let go, because
        that failure really may be the sibling's."""
        self._seed_red()
        self._a_real_siblings_entry()
        self.assertIsNone(self._stop("tdd_stop_gate.py"))


class TestTheSprintGateStopsDeferringOnIt(_OwnSessionGateE2ECase):
    """`sprint_stop_gate.py`, the other consumer of the same predicate.

    Its deferral is a list of reasons to postpone the accept nudge, and "a
    teammate is still working" was answering yes to an entry of ours. Every
    other leg is left unarmed — no dialogue marker, no review mid-cycle, no
    registered teammate — so the entry is the only thing that can decide the
    answer and a pass cannot be borrowed from a neighbour.
    """

    def _seed_a_story_to_accept(self) -> None:
        (self.smm_dir / "sprint.json").write_text(SPRINT_IN_PROGRESS)
        (self.smm_dir / ".accept").write_text("done")

    def test_our_own_subagents_entry_no_longer_defers_the_nudge(self):
        self._seed_a_story_to_accept()
        self._our_subagents_entry()
        decision = self._stop("sprint_stop_gate.py")
        self.assertIsNotNone(decision, "the nudge was deferred on an entry of ours")
        assert decision is not None
        self.assertEqual(decision["decision"], "block")

    def test_a_real_sibling_still_defers_it(self):
        """Over-arming control, and the behaviour the gate must keep: while a
        teammate is genuinely working, the lead is not nudged to accept a sprint
        that teammate is still adding to."""
        self._seed_a_story_to_accept()
        self._a_real_siblings_entry()
        self.assertIsNone(self._stop("sprint_stop_gate.py"))
