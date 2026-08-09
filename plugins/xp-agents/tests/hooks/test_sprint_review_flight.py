#!/usr/bin/env python3
"""Tests for the in-flight record a running sprint reviewer leaves behind.

The sprint-review gate clears on a sprint_end event, and the reviewer is an
Agent-tool subagent, which the harness backgrounds. Between "the reviewer was
never invoked" and "the reviewer is running right now" the gate saw no
difference, so it told the agent to run what it had just run.

This suite pins the evidence that separates the two. It is the second instance
of the pattern `housekeeping_flight` established, and the near-identical shape
is deliberate — see that module's docstring for the design and
`sprint_review_flight`'s for what differs here (two states, not three).

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

import hook_liveness
import housekeeping_flight
import marker_names
import markers
import session_markers
import sprint_review_flight
from conftest import _HookTestCase

_SESSION = "session-under-test"
_OTHER_SESSION = "some-other-session"

# Explicit clock. NOW is arbitrary; STALE_AT sits far enough behind it that the
# record is past the window whatever the window is set to.
NOW = 1_000_000.0
STALE_AT = NOW - sprint_review_flight.STALE_AFTER_SECONDS - 1
FRESH_AT = NOW - 1.0


class _FlightTestCase(_HookTestCase):
    """Shared record plumbing: write one, read it back through the module."""

    def record_path(self, session_id: str = _SESSION) -> Path:
        return markers.marker_path(
            self.smm_dir, sprint_review_flight.marker(session_id)
        )

    def write_record(self, session_id: str = _SESSION, started_at: float = FRESH_AT):
        markers.marker_write(
            self.smm_dir,
            sprint_review_flight.marker(session_id),
            {"session_id": session_id, "started_at": started_at},
        )

    def write_raw(self, data: dict | str, session_id: str = _SESSION) -> None:
        """Plant a record the normal writer would never produce."""
        raw = data if isinstance(data, str) else json.dumps(data)
        self.record_path(session_id).write_text(raw, encoding="utf-8")

    def fresh(self, session_id: str = _SESSION, now: float = NOW) -> bool:
        return sprint_review_flight.is_fresh(
            self.smm_dir, {"session_id": session_id}, now
        )


class TestFreshness(_FlightTestCase):
    """The one question the gate asks: is a reviewer running right now?"""

    def test_a_record_inside_the_window_is_fresh(self):
        self.write_record()
        self.assertTrue(self.fresh())

    def test_no_record_is_not_fresh(self):
        self.assertFalse(self.fresh())

    def test_an_aged_out_record_is_not_fresh(self):
        self.write_record(started_at=STALE_AT)
        self.assertFalse(self.fresh())

    def test_exactly_at_the_window_is_not_fresh(self):
        # Fail closed on the boundary: `>=` the window, not `>`. A gate that
        # goes on suppressing at the boundary is a gate that never fires.
        self.write_record(started_at=NOW - sprint_review_flight.STALE_AFTER_SECONDS)
        self.assertFalse(self.fresh())

    def test_a_future_timestamp_is_not_fresh(self):
        # The window needs a LOWER bound too. A future stamp ages negative, and
        # an upper-bound-only check would call that fresh for the rest of the
        # session — the gate would then be suppressed forever and the sprint
        # review skipped in silence, which is worse than the defect being
        # fixed. Milliseconds where seconds were meant is the cheapest way to
        # produce one; a backwards clock step is the other.
        for label, started_at in (
            ("milliseconds", NOW * 1000),
            ("one day ahead", NOW + 86400),
            ("a hair ahead", NOW + 0.5),
        ):
            with self.subTest(started_at=label):
                self.write_record(started_at=started_at)
                self.assertFalse(self.fresh())

    def test_unusable_timestamps_are_not_fresh(self):
        # `bool` is an `int` subclass, and `json.loads` accepts Infinity/NaN by
        # default — none of the three compares True against the threshold, so
        # an unguarded check would fail OPEN and read a record it cannot age as
        # a reviewer still working.
        for label, raw in (
            ("missing", '{"session_id": "s"}'),
            ("non-numeric", '{"session_id": "s", "started_at": "just now"}'),
            ("boolean", '{"session_id": "s", "started_at": true}'),
            ("infinity", '{"session_id": "s", "started_at": Infinity}'),
            ("nan", '{"session_id": "s", "started_at": NaN}'),
        ):
            with self.subTest(timestamp=label):
                self.write_raw(raw)
                self.assertFalse(self.fresh())

    def test_corrupt_json_is_not_fresh(self):
        self.write_raw("{not json")
        self.assertFalse(self.fresh())

    def test_a_record_written_now_reads_fresh_against_the_real_clock(self):
        # The default `now` is the real clock, which is what every production
        # caller uses. A frozen-clock-only suite would pass against a module
        # that never reads the wall clock at all.
        self.write_record(started_at=time.time())
        self.assertTrue(
            sprint_review_flight.is_fresh(self.smm_dir, {"session_id": _SESSION})
        )


class TestSessionScoping(_FlightTestCase):
    """The SMM is shared across worktrees and windows, so the record is keyed."""

    def test_another_sessions_record_does_not_read_as_ours(self):
        self.write_record(session_id=_OTHER_SESSION)
        self.assertFalse(self.fresh())

    def test_marker_name_differs_per_session(self):
        self.assertNotEqual(
            sprint_review_flight.marker(_SESSION).name,
            sprint_review_flight.marker(_OTHER_SESSION).name,
        )

    def test_absent_session_id_falls_back_to_the_shared_marker(self):
        # A host that exposes no id gets the unsuffixed marker and the
        # time-only check it was always going to get — not a crash.
        for value in (None, "", "   ", 17):
            with self.subTest(value=value):
                self.assertEqual(
                    sprint_review_flight.marker(value).name,
                    marker_names.SPRINT_REVIEW_IN_FLIGHT,
                )

    def test_the_record_is_not_the_housekeepers(self):
        # Two records, two windows, two lifecycles. One name would let a
        # running housekeeper suppress the sprint-review gate.
        self.assertNotEqual(
            sprint_review_flight.marker(_SESSION).name,
            housekeeping_flight.marker(_SESSION).name,
        )


class TestRecordAndInputGlobsAreDisjoint(_FlightTestCase):
    """The two sprint-review stems must not see each other's files.

    `subagent_stop` globs the sprint-review INPUT prefix and unlinks every hit;
    the session sweep globs the in-flight stem and unlinks what it can age.
    Either stem becoming a prefix of the other makes one glob eat the other's
    file, and nothing else in the tree would notice.
    """

    def test_the_input_glob_does_not_see_a_record(self):
        self.write_record()
        matched = self.smm_dir.glob(f"{marker_names.SPRINT_REVIEW_INPUT_PREFIX}*")
        self.assertEqual([p.name for p in matched], [])

    def test_the_record_glob_does_not_see_an_input_file(self):
        (self.smm_dir / f"{marker_names.SPRINT_REVIEW_INPUT_PREFIX}json").write_text(
            "{}", encoding="utf-8"
        )
        matched = self.smm_dir.glob(f"{marker_names.SPRINT_REVIEW_IN_FLIGHT}*")
        self.assertEqual([p.name for p in matched], [])


class TestRecordStart(_FlightTestCase):
    """The write half, driven through the module's own writer."""

    def test_a_started_record_reads_fresh(self):
        sprint_review_flight.record_start(self.smm_dir, {"session_id": _SESSION})
        self.assertTrue(
            sprint_review_flight.is_fresh(self.smm_dir, {"session_id": _SESSION})
        )

    def test_the_record_carries_a_timestamp(self):
        sprint_review_flight.record_start(self.smm_dir, {"session_id": _SESSION})
        record = markers.marker_read(
            self.smm_dir, sprint_review_flight.marker(_SESSION)
        )
        assert isinstance(record, dict)
        self.assertIn("started_at", record)

    def test_a_failed_write_never_raises(self):
        # This runs from a SubagentStart injector with no top-level guard:
        # recording that the reviewer started must not be the thing that stops
        # it starting. A dropped record reads downstream as "never invoked",
        # which fails closed.
        sprint_review_flight.record_start(
            Path("/nonexistent-smm-dir"), {"session_id": _SESSION}
        )


class TestConsume(_FlightTestCase):
    """The record must not outlive the run it describes."""

    def test_consume_removes_the_record(self):
        self.write_record()
        sprint_review_flight.consume(self.smm_dir, {"session_id": _SESSION})
        self.assertFalse(self.record_path().exists())

    def test_consume_with_no_record_is_harmless(self):
        self.assertIsNone(
            sprint_review_flight.consume(self.smm_dir, {"session_id": _SESSION})
        )


class TestWindowSize(unittest.TestCase):
    """The window is calibrated between the two neighbours it sits between.

    Pinning the literal would only restate the assignment. What carries meaning
    is the ordering the number was chosen for: longer than the housekeeping
    window because a sprint review reads a whole sprint's events and rewrites
    milestone delivery, and far shorter than the hook-liveness window because
    this asks "is this one subagent still working", not "is the runtime alive".
    """

    def test_longer_than_the_housekeeping_window(self):
        self.assertGreater(
            sprint_review_flight.STALE_AFTER_SECONDS,
            housekeeping_flight.STALE_AFTER_SECONDS,
        )

    def test_far_shorter_than_the_liveness_window(self):
        self.assertLess(
            sprint_review_flight.STALE_AFTER_SECONDS,
            hook_liveness.STALE_AFTER_SECONDS,
        )


class TestSessionBoundarySweep(_FlightTestCase):
    """An armed record that is never consumed must not suppress forever.

    A reviewer that dies between SubagentStart and SubagentStop never runs its
    own consume — and that is the common case here, not the rare one, since it
    is the very failure this record was built to notice.

    The glob spans EVERY session's record, and the SMM is shared: a second
    window on the same repo resolves the same project id. So the sweep is
    bounded by freshness, exactly as `housekeeping_flight.sweep_orphan_records`
    is — a record still inside its window may have a reviewer running behind it.

    These drive the SessionStart sweep itself, not the module function, because
    a sweep that is never registered clears nothing however correct it is.
    """

    def test_sweep_clears_an_orphaned_record(self):
        self.write_record(started_at=STALE_AT)
        session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse(self.record_path().exists())

    def test_sweep_clears_another_dead_sessions_record(self):
        self.write_record(session_id=_OTHER_SESSION, started_at=STALE_AT)
        session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse(self.record_path(_OTHER_SESSION).exists())

    def test_sweep_clears_the_unsuffixed_record(self):
        markers.marker_write(
            self.smm_dir,
            markers.MarkerDef(marker_names.SPRINT_REVIEW_IN_FLIGHT, "json"),
            {"started_at": 1.0},
        )
        session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse((self.smm_dir / marker_names.SPRINT_REVIEW_IN_FLIGHT).exists())

    def test_sweep_keeps_a_fresh_record_owned_by_a_live_session(self):
        # A second window's SessionStart must not retire a running reviewer's
        # record: its owner's next Stop would then read "never invoked" and the
        # lead would start a second review over the one still running.
        self.write_record(session_id=_OTHER_SESSION, started_at=time.time())
        session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertTrue(self.record_path(_OTHER_SESSION).exists())

    def test_sweep_leaves_an_unageable_record_to_be_cleared(self):
        # Same rule as the freshness read: a record we cannot age is not
        # evidence that anything is running, so it goes.
        self.write_raw('{"session_id": "s", "started_at": "just now"}')
        session_markers.sweep_stale_session_markers(self.smm_dir)
        self.assertFalse(self.record_path().exists())


if __name__ == "__main__":
    unittest.main()
