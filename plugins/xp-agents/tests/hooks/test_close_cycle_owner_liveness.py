#!/usr/bin/env python3
"""The owning session, not a duration, decides an abandoned close cycle.

WHY A DURATION COULD NOT. The close-cycle marker is not session-scoped and the
SMM is shared across windows and worktrees, so any detector routinely sees a
cycle that is LIVE somewhere else. The first fix for that gave the marker an
age threshold — but a close's runtime is unbounded, and the very close that
shipped the threshold ran 4429 seconds while perfectly healthy, past the hour
it allowed. Past that boundary the regression reopened unchanged: a second
window files a high-severity concern inside a live close's counting window,
flipping its merge gate to Abort, and consumes the marker, disarming its Stop
gate. No fixed duration is simultaneously long enough for a slow live close and
short enough for a dead one.

WHAT REPLACES IT. Every session writes a per-session heartbeat into this same
shared SMM, so arming stamps the marker with the session that owns the close
and a detector in another window asks that session directly. Age survives only
as the fallback for a marker whose owner cannot be named — one armed by an
older plugin version — or whose heartbeat cannot be read.

The two mistakes are NOT symmetric, and the fallback's direction follows from
that: a false record breaks a healthy close, while a missed one is only the
silent loss that predates this module. So "cannot tell" never records on its
own; it defers to age.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import close_cycle_abandonment
import hook_liveness
import markers
from _abandonment_fixtures import _AbandonmentAssertions, arm_abandoned
from conftest import _HookTestCase

_OWNER = "owner-session-id"


class _OwnerCase(_AbandonmentAssertions, _HookTestCase):
    """Arms a marker owned by a named session, with that session's heartbeat."""

    def arm_owned(self, owner: str = _OWNER, *, aged: bool = False) -> None:
        """Arm carrying `owner`; optionally back-date past the age rule."""
        if aged:
            arm_abandoned(self.smm_dir, owner)
        else:
            markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, owner)

    def beat(self, owner: str = _OWNER, *, stale: bool = False) -> None:
        """Write `owner`'s heartbeat, optionally old enough to read as stopped."""
        hook_liveness.write_heartbeat(self.smm_dir, session_id=owner)
        if stale:
            self._restamp(owner, -hook_liveness.STALE_AFTER_SECONDS - 60)

    def beat_at_offset(self, offset: float, owner: str = _OWNER) -> None:
        """Write `owner`'s heartbeat stamped `offset` seconds from now.

        A positive offset dates it in the FUTURE. `owner_session_is_live` reads
        the clock itself rather than taking a `now`, so a future timestamp is
        the only way to reach a negative age — the same shape
        `test_hook_heartbeat_marker` uses for its far-future legs.
        """
        hook_liveness.write_heartbeat(self.smm_dir, session_id=owner)
        self._restamp(owner, offset)

    def _restamp(self, owner: str, offset: float) -> None:
        path = markers.marker_path(self.smm_dir, hook_liveness.heartbeat_marker(owner))
        markers.marker_write(
            self.smm_dir,
            hook_liveness.heartbeat_marker(owner),
            {"written_at": path.stat().st_mtime + offset},
        )

    def record(self) -> bool:
        return close_cycle_abandonment.record_abandonment(
            self.smm_dir, close_cycle_abandonment.DETECTOR_SESSION_SWEEP
        )


class TestAFutureHeartbeatIsNotEvidenceOfLife(_OwnerCase):
    """A negative age must not read as fresh.

    `session_markers.marker_age_seconds` hands a future timestamp back as a
    negative number on purpose and says so: "Callers own the BOUNDS ... any
    caller that must fail CLOSED has to bound it below." `hook_liveness` and
    the two in-flight gates all bound it; this reader did not, so a heartbeat
    stamped in milliseconds, or written across a backwards clock step, aged
    negative and read live.

    Live is the dangerous verdict here: it suppresses the age fallback
    entirely, so the close-cycle Stop gate stays armed with nothing able to
    release it, and the next close's preload overwrites the marker it should
    have recorded. Bounded in practice only by another session's heartbeat
    write, which reaps an out-of-window sibling.
    """

    def test_a_millisecond_timestamp_does_not_read_as_live(self):
        """The observed shape: seconds recorded as milliseconds."""
        self.arm_owned(aged=True)
        self.beat_at_offset(time.time() * 1000)

        self.assertIsNone(
            close_cycle_abandonment.owner_session_is_live(self.smm_dir, _OWNER)
        )

    def test_a_future_heartbeat_falls_back_to_the_age_rule(self):
        """None, not False: the owner is unreadable, not proven dead."""
        self.arm_owned(aged=True)
        self.beat_at_offset(hook_liveness.FUTURE_SKEW_GRACE_SECONDS + 60)

        self.assertIsNone(
            close_cycle_abandonment.owner_session_is_live(self.smm_dir, _OWNER)
        )
        self.assertTrue(self.record(), "an aged marker must still record")

    def test_ordinary_clock_slew_is_still_live(self):
        """The non-vacuity leg. Bounding below must not start false-recording
        abandonment on the small forward skew a normal machine produces —
        that is the failure that gets a liveness check switched off."""
        self.arm_owned(aged=True)
        self.beat_at_offset(hook_liveness.FUTURE_SKEW_GRACE_SECONDS - 1)

        self.assertTrue(
            close_cycle_abandonment.owner_session_is_live(self.smm_dir, _OWNER)
        )
        self.assertFalse(self.record(), "a live owner is never abandoned")


class TestALiveOwnerIsNeverAbandoned(_OwnerCase):
    """The regression the age rule only delayed."""

    def test_an_aged_marker_whose_owner_is_live_records_nothing(self):
        """THE test. Old enough for the age rule, alive by its owner.

        This is the exact shape that broke: a long-running but healthy close,
        seen from a second window. Under the age rule alone this recorded and
        consumed. It must now do neither.
        """
        self.arm_owned(aged=True)
        self.beat()

        self.assertFalse(self.record(), "a live owner is a running close")
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "the live close's Stop gate must stay armed — consuming here is "
            "what silently disarmed it",
        )

    def test_a_young_marker_whose_owner_is_live_records_nothing(self):
        self.arm_owned()
        self.beat()
        self.assertFalse(self.record())
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE))


class TestADeadOwnerIsAbandonedAtAnyAge(_OwnerCase):
    """The other half: liveness must not become a way to never record."""

    def test_a_stale_owner_heartbeat_records_even_when_the_marker_is_young(self):
        """A cycle that died seconds ago is still dead.

        Under the age rule this waited an hour to be detectable. Owner
        liveness answers immediately, which is the half a duration got wrong
        in the other direction.
        """
        self.arm_owned()
        self.beat(stale=True)

        self.assertTrue(self.record(), "a stopped owner is an abandoned cycle")
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        )
        concern = self._one_bypass_concern()
        self.assertEqual(
            concern["metadata"]["detector"],
            close_cycle_abandonment.DETECTOR_SESSION_SWEEP,
        )


class TestTheFallbackWhenTheOwnerCannotBeNamed(_OwnerCase):
    """A marker from an older version carries no owner. Age still decides."""

    def test_an_unowned_aged_marker_still_records(self):
        arm_abandoned(self.smm_dir, "")
        self.assertTrue(self.record(), "age is the fallback, not dead code")

    def test_an_unowned_young_marker_records_nothing(self):
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")
        self.assertFalse(self.record())
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE))

    def test_an_owner_with_no_heartbeat_at_all_falls_back_to_age(self):
        """Cannot tell — so defer to age rather than guess.

        A named owner whose heartbeat was reaped is indistinguishable from one
        that never wrote one. Recording on 'cannot tell' would put the false
        record straight back.
        """
        self.arm_owned(aged=True)
        self.assertTrue(self.record(), "aged + undeterminable falls back to age")

    def test_an_owner_with_no_heartbeat_and_a_young_marker_records_nothing(self):
        self.arm_owned()
        self.assertFalse(
            self.record(),
            "undeterminable liveness must never record on its own — that is "
            "the direction the two mistakes are asymmetric in",
        )


class TestArmingStampsTheOwner(_OwnerCase):
    """Without the payload, `owner_session_is_live` has nothing to ask about."""

    def test_arm_close_cycle_writes_the_resolved_session_id(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"XP_SESSION_ID": "armed-by-me"}):
            close_cycle_abandonment.arm_close_cycle(self.smm_dir)

        self.assertEqual(
            markers.marker_read(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "armed-by-me",
        )

    def test_an_unresolvable_session_arms_empty_rather_than_refusing(self):
        from unittest.mock import patch

        with patch.object(hook_liveness, "resolve_session_id", return_value=None):
            close_cycle_abandonment.arm_close_cycle(self.smm_dir)

        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "arming must never fail closed — an unowned marker is decidable "
            "by age, an unarmed one gates nothing at all",
        )


if __name__ == "__main__":
    unittest.main()
