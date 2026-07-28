#!/usr/bin/env python3
"""Tests for the Stop housekeeping gate and the in-flight record it reads.

The gate used to know two states: the need marker is armed, or it is not.
Agent-tool subagents are backgrounded, so "the housekeeper is running right
now" looked identical to "nobody ever invoked it" and the gate told the lead
to invoke an agent already in flight. `housekeeping_flight` explains the
bounded-window design; this suite pins the behaviour.

This is the single home for gate regressions — the duplicate class in
test_stop_gates.py was removed when this file was added.

Staleness is seeded with an explicit past timestamp, never with `sleep`.
"""

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import housekeeping_flight
import housekeeping_stop_gate
import marker_names
import markers
import materialize
import subagent_start
import subagent_stop
from _hook_inputs import _make_stop_input
from _kickoff_skill import _SKILL_MD
from conftest import _HookTestCase

_SESSION = "session-under-test"
_OTHER_SESSION = "some-other-session"

# Explicit clock. NOW is arbitrary; STALE_AT sits far enough behind it that the
# record is past the window whatever the window is set to.
NOW = 1_000_000.0
STALE_AT = NOW - housekeeping_flight.STALE_AFTER_SECONDS - 1
FRESH_AT = NOW - 1.0


class _GateTestCase(_HookTestCase):
    """Shared setup: the need armed, no in-flight record yet."""

    def setUp(self):
        super().setUp()
        markers.marker_write(self.smm_dir, markers.NEEDS_HOUSEKEEPING, "")

    def gate(self, session_id: str = _SESSION, now: float = NOW, **overrides):
        payload = _make_stop_input(session_id=session_id, **overrides)
        return housekeeping_stop_gate.run(payload, smm_dir=self.smm_dir, now=now)

    def record_path(self, session_id: str = _SESSION) -> Path:
        return markers.marker_path(self.smm_dir, housekeeping_flight.marker(session_id))

    def write_record(self, session_id: str = _SESSION, started_at: float = FRESH_AT):
        markers.marker_write(
            self.smm_dir,
            housekeeping_flight.marker(session_id),
            {
                "session_id": session_id,
                "started_at": started_at,
                "curation_watermark": "",
            },
        )

    def write_raw(self, data: dict | str, session_id: str = _SESSION) -> None:
        """Plant a record the normal writer would never produce."""
        raw = data if isinstance(data, str) else json.dumps(data)
        self.record_path(session_id).write_text(raw, encoding="utf-8")

    def start_housekeeper(self, agent_type: str = "xp-housekeeper") -> None:
        subagent_start.run(
            {
                "session_id": _SESSION,
                "agent_id": "housekeeper-1",
                "agent_type": agent_type,
                "hook_event_name": "SubagentStart",
                "cwd": str(self.smm_dir),
            },
            smm_dir=self.smm_dir,
        )

    def stop_housekeeper(self) -> None:
        subagent_stop.run(
            {
                "session_id": _SESSION,
                "agent_id": "housekeeper-1",
                "agent_type": "xp-housekeeper",
                "last_assistant_message": "",
            },
            smm_dir=self.smm_dir,
        )


class TestNeverInvoked(_GateTestCase):
    """AC#2 — the need is armed and nothing has started."""

    def test_blocks_with_todays_message_verbatim(self):
        # Verbatim against the constant, not a paraphrase: this is the wording
        # the lead already knows means "you have not started it yet".
        self.assertEqual(self.gate(), housekeeping_stop_gate._BLOCK_MESSAGE)


class TestInFlightFresh(_GateTestCase):
    """AC#3 — a record for THIS session, inside the window."""

    def test_passes_so_the_lead_can_end_the_turn(self):
        self.write_record()
        self.assertIsNone(self.gate())


class TestInFlightStale(_GateTestCase):
    """AC#4 — the record aged out. Block, but say something different."""

    def test_blocks_with_the_stale_message(self):
        self.write_record(started_at=STALE_AT)
        self.assertEqual(self.gate(), housekeeping_stop_gate._STALE_MESSAGE)

    def test_stale_wording_differs_from_never_invoked(self):
        # The difference IS the point. If both states said the same thing the
        # lead would wait again and the gate would be back where it started.
        self.assertNotEqual(
            housekeeping_stop_gate._STALE_MESSAGE,
            housekeeping_stop_gate._BLOCK_MESSAGE,
        )

    def test_stale_wording_tells_the_lead_to_reinvoke(self):
        self.assertIn("re-invoke", housekeeping_stop_gate._STALE_MESSAGE.lower())

    def test_exactly_at_the_window_is_stale(self):
        # Fail closed on the boundary: `>=` the window, not `>`.
        self.write_record(started_at=NOW - housekeeping_flight.STALE_AFTER_SECONDS)
        self.assertEqual(self.gate(), housekeeping_stop_gate._STALE_MESSAGE)

    def test_a_future_timestamp_is_stale_not_fresh(self):
        # The window needs a LOWER bound too. A future stamp ages negative, and
        # an upper-bound-only check calls that fresh for the rest of the
        # session — the gate would pass every turn and curation would be
        # skipped in silence. Milliseconds where seconds were meant is the
        # cheapest way to produce one; a backwards clock step is the other.
        for label, started_at in (
            ("milliseconds", NOW * 1000),
            ("one day ahead", NOW + 86400),
            ("a hair ahead", NOW + 0.5),
        ):
            with self.subTest(started_at=label):
                self.write_record(started_at=started_at)
                self.assertEqual(self.gate(), housekeeping_stop_gate._STALE_MESSAGE)


class TestMalformedRecord(_GateTestCase):
    """The two malformed shapes block with DIFFERENT messages.

    A single shared assertion across both would fail, and the tempting fix
    would be to loosen it. They are genuinely different states.
    """

    def test_corrupt_json_reads_as_never_invoked(self):
        # `marker_read` collapses unparseable JSON to None, so there is no
        # record at all — that is the never-invoked path, verbatim message.
        self.write_raw("{not json")
        self.assertEqual(self.gate(), housekeeping_stop_gate._BLOCK_MESSAGE)

    def test_unusable_timestamps_read_as_stale(self):
        # Well-formed record, unusable timestamp: something DID start, we just
        # cannot age it. Fold toward stale so the lead re-invokes.
        #
        # `bool` is an `int` subclass, and `json.loads` accepts Infinity/NaN by
        # default — none of the three compares True against the threshold, so
        # an unguarded check would fail OPEN and report a dead housekeeper as
        # freshly in flight.
        for label, raw in (
            ("missing", '{"session_id": "s"}'),
            ("non-numeric", '{"session_id": "s", "started_at": "just now"}'),
            ("boolean", '{"session_id": "s", "started_at": true}'),
            ("infinity", '{"session_id": "s", "started_at": Infinity}'),
            ("nan", '{"session_id": "s", "started_at": NaN}'),
        ):
            with self.subTest(timestamp=label):
                self.write_raw(raw)
                self.assertEqual(self.gate(), housekeeping_stop_gate._STALE_MESSAGE)


class TestSessionScoping(_GateTestCase):
    """The SMM is shared across worktrees and sessions."""

    def test_another_sessions_record_does_not_count(self):
        self.write_record(session_id=_OTHER_SESSION)
        self.assertEqual(self.gate(), housekeeping_stop_gate._BLOCK_MESSAGE)

    def test_marker_name_differs_per_session(self):
        self.assertNotEqual(
            housekeeping_flight.marker(_SESSION).name,
            housekeeping_flight.marker(_OTHER_SESSION).name,
        )

    def test_absent_session_id_falls_back_to_the_shared_marker(self):
        # A host that exposes no id gets the unsuffixed marker and the
        # time-only check it was always going to get — not a crash.
        for value in (None, "", "   ", 17):
            with self.subTest(value=value):
                self.assertEqual(
                    housekeeping_flight.marker(value).name,
                    marker_names.HOUSEKEEPING_IN_FLIGHT,
                )


class TestRealSubagentStartRoundTrip(_GateTestCase):
    """AC#5 — drive the WRITE half for real, then read it with the gate.

    Hand-writing the record and exercising only the gate passes identically
    against a `subagent_start.py` that writes nothing. That tests
    reachability, not behaviour. This is the case that is red before the
    change and green after.

    The real writer stamps the real clock, so these read with the real clock
    too. Reading a real write against the frozen NOW dates the record decades
    in the FUTURE, which a lower-bounded window correctly calls stale — the
    gate would then be judged on a timestamp no writer could produce.
    """

    def gate(self, session_id: str = _SESSION, now: float | None = None, **overrides):
        return super().gate(
            session_id, time.time() if now is None else now, **overrides
        )

    def test_gate_passes_after_a_real_subagent_start(self):
        self.start_housekeeper()
        self.assertIsNone(self.gate())

    def test_qualified_agent_type_also_records(self):
        self.start_housekeeper(agent_type="xp-agents:xp-housekeeper")
        self.assertIsNone(self.gate())

    def test_record_captures_the_starting_curation_watermark(self):
        # The watermark snapshot is what lets SubagentStop tell a housekeeper
        # that finalized from one that died partway.
        self.start_housekeeper()
        record = markers.marker_read(self.smm_dir, housekeeping_flight.marker(_SESSION))
        assert isinstance(record, dict)
        self.assertIn("curation_watermark", record)
        self.assertIn("started_at", record)

    def test_a_different_agent_type_records_nothing(self):
        self.start_housekeeper(agent_type="xp-code-reviewer")
        self.assertEqual(self.gate(), housekeeping_stop_gate._BLOCK_MESSAGE)


class TestFailedHousekeeperDoesNotReportDone(_GateTestCase):
    """AC#7 — SubagentStop fires for a subagent that DIED, not just one that finished.

    The handler used to key only on `agent_type` and never ask whether the run
    succeeded, so a crashed housekeeper consumed the need without curating —
    the same silent skip by a different door.

    There is no success field to gate on. Verified empirically against Claude
    Code 2.1.220 by capturing a real SubagentStop payload from a hook: the
    fields delivered are session_id, transcript_path, cwd, prompt_id,
    permission_mode, agent_id, agent_type, hook_event_name, stop_hook_active,
    agent_transcript_path, last_assistant_message, background_tasks and
    session_crons. None reports success or failure, and the hooks reference
    documents no such field either. So the check uses the artifact instead —
    see `housekeeping_flight.finalized`.
    """

    def finalize_curation(self) -> None:
        """What `smm_cli complete-curation` does to the watermark."""
        materialize.write_curation_watermark(self.smm_dir, 7, "xp-housekeeper")

    def test_gate_still_blocks_as_never_invoked_after_a_failed_run(self):
        # Never-invoked wording, not stale wording: the record is gone, so the
        # lead is being told to start one, which is exactly right. This also
        # implies the need marker survived.
        self.start_housekeeper()
        self.stop_housekeeper()
        self.assertEqual(self.gate(), housekeeping_stop_gate._BLOCK_MESSAGE)

    def test_record_is_cleared_even_on_failure(self):
        # Otherwise the stale record would outlive the run and the NEXT Stop
        # would report "stalled" about a housekeeper that is already gone.
        self.start_housekeeper()
        self.stop_housekeeper()
        self.assertFalse(self.record_path().exists())

    def test_failure_is_recorded_as_an_event_not_swallowed(self):
        self.start_housekeeper()
        self.stop_housekeeper()
        events = _common.read_events_locked(self.smm_dir, "test-hk-gate")
        self.assertTrue(
            any("did not finalize" in e.get("content", "").lower() for e in events),
            "a housekeeper that failed to curate must leave a trace",
        )

    def test_finalized_run_consumes_the_need(self):
        self.start_housekeeper()
        self.finalize_curation()
        self.stop_housekeeper()
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.NEEDS_HOUSEKEEPING)
        )
        self.assertIsNone(self.gate())

    def test_finalized_run_clears_the_record(self):
        self.start_housekeeper()
        self.finalize_curation()
        self.stop_housekeeper()
        self.assertFalse(self.record_path().exists())

    def test_no_record_falls_back_to_consuming(self):
        # Degraded path: the record write was dropped, or SubagentStart never
        # ran. With no start-side reference point there is nothing to compare,
        # so behave exactly as before this story rather than latching the need
        # on forever — refusing here would be an unbreakable livelock.
        self.stop_housekeeper()
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.NEEDS_HOUSEKEEPING)
        )


class TestCompleted(_GateTestCase):
    """AC#6 — the need is consumed and the record cleared."""

    def test_passes_when_both_are_gone(self):
        markers.marker_consume(self.smm_dir, markers.NEEDS_HOUSEKEEPING)
        self.assertIsNone(self.gate())

    def test_passes_when_need_gone_even_if_a_record_lingers(self):
        # The need marker is the outer gate and still short-circuits first.
        self.write_record()
        markers.marker_consume(self.smm_dir, markers.NEEDS_HOUSEKEEPING)
        self.assertIsNone(self.gate())


class TestExistingEarlyReturns(_GateTestCase):
    """Regressions the gate already had and this story must not narrow away."""

    def test_xp_agent_defers(self):
        self.assertIsNone(self.gate(agent_type="xp-code-reviewer"))

    def test_stop_hook_active_defers(self):
        self.assertIsNone(self.gate(stop_hook_active=True))

    def test_missing_smm_defers(self):
        self.assertIsNone(
            housekeeping_stop_gate.run(
                _make_stop_input(), smm_dir=Path("/nonexistent-smm")
            )
        )

    def test_asking_user_defers(self):
        # This is what makes "Chat about this..." work on AskUserQuestion.
        markers.marker_write(self.smm_dir, markers.ASKING_USER, "")
        self.assertIsNone(self.gate())

    def test_asking_user_defers_even_with_a_stale_record(self):
        markers.marker_write(self.smm_dir, markers.ASKING_USER, "")
        self.write_record(started_at=STALE_AT)
        self.assertIsNone(self.gate())


class TestSessionBoundarySweep(_GateTestCase):
    """Session-suffixed records must not accumulate forever.

    A session that dies between SubagentStart and SubagentStop never runs its
    own consume — and that is the common case here, not the rare one, since it
    is the very failure this gate was built to notice.
    """

    def test_sweep_clears_suffixed_records_from_dead_sessions(self):
        self.write_record(session_id=_OTHER_SESSION)
        markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse(self.record_path(_OTHER_SESSION).exists())

    def test_sweep_clears_the_unsuffixed_record(self):
        markers.marker_write(
            self.smm_dir, markers.HOUSEKEEPING_IN_FLIGHT, {"started_at": 1.0}
        )
        markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.HOUSEKEEPING_IN_FLIGHT)
        )


class TestMarkerConstant(unittest.TestCase):
    """The new constant follows the dotfile convention its siblings do."""

    def test_well_formed_dotfile(self):
        value = marker_names.HOUSEKEEPING_IN_FLIGHT
        self.assertIsInstance(value, str)
        self.assertTrue(value.startswith("."))
        self.assertNotIn(" ", value)

    def test_registered_for_the_session_boundary_sweep(self):
        self.assertIn(markers.HOUSEKEEPING_IN_FLIGHT, markers._STALE_SESSION_MARKERS)


class TestFreshnessWindowIsBounded(unittest.TestCase):
    """The window is the ONLY mid-session protection, so it must be short.

    `_STALE_SESSION_MARKERS` membership is correct housekeeping but not a
    backstop: that sweep is gated to fresh-start SessionStart, and the
    abandonment this gate reads happens mid-session.
    """

    def test_window_is_minutes_not_hours(self):
        self.assertGreater(housekeeping_flight.STALE_AFTER_SECONDS, 60)
        self.assertLessEqual(housekeeping_flight.STALE_AFTER_SECONDS, 30 * 60)


class TestKickoffProseNamesARealParameter(unittest.TestCase):
    """AC#8 — kickoff must not instruct a parameter the Agent tool rejects.

    Probed empirically on Claude Code 2.1.220 rather than inferred from the
    docs: `run_in_background: false` IS accepted and DOES run the subagent
    synchronously, while the `background: false` agent-frontmatter key is
    ignored (the agent still launches async). So the lever the prose names is
    the real one and must stay; what must not appear is the frontmatter key,
    which would read as a working fix and silently do nothing.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = _SKILL_MD.read_text(encoding="utf-8")

    def test_names_the_tool_parameter_that_works(self):
        self.assertIn("run_in_background", self.text)

    def test_does_not_prescribe_the_inert_frontmatter_key(self):
        self.assertNotIn("background: false", self.text)

    def test_does_not_claim_the_lever_is_guaranteed(self):
        # The gate exists precisely because the prose lever is LLM-followed,
        # not enforced. Prose that promises otherwise is what let the race
        # look like lead error.
        self.assertNotIn("guarantee", self.text.lower())


if __name__ == "__main__":
    unittest.main()
