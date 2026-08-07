#!/usr/bin/env python3
"""The liveness READ stops trusting a heartbeat it cannot address.

Every writer keys the heartbeat on the session id its payload carried. The
reader is a shell subprocess with no payload, so its only signal is the
environment — and when that resolves nothing, the reader addressed the shared
unsuffixed marker, missed, and then accepted ANY fresh sibling as proof that
ITS OWN runtime was live. A session enforcing nothing reads LIVE off a
neighbour's heartbeat, which is the exact silent unenforcement this whole
mechanism exists to make loud.

Two copies of that borrow shipped: one on the absent path, one on the stale
path. This suite pins both closed, plus the reason text the newly-refusing
path has to carry.

Cited rather than repeated — one contract, one home:

- an id-less host reading its OWN shared marker stays live (the no-brick
  guarantee) ..... test_hook_heartbeat_marker.py::TestDegradesToTimeOnly
- two session-id variables that disagree still REFUSE
  ......... test_hook_heartbeat_liveness.py::TestDisagreeingSessionIdsRefuse
- a session that owns its heartbeat reads live, naming no missing variable
  .... test_hook_heartbeat_marker.py::test_matching_id_and_fresh_is_live
- a run where no hook ever executed names the likely cause
  .... test_hook_heartbeat_marker.py::test_absent_marker_reason_names_the_likely_cause
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

import hook_liveness
from _heartbeat_fixtures import env as _env
from conftest import _HookTestCase


class _ReadRepairCase(_HookTestCase):
    """One SMM, one foreign session, and a reader that can name nobody."""

    NOW = 1_000_000.0
    FOREIGN = "a-session-that-is-not-ours"

    def _foreign_heartbeat(self, at: float) -> None:
        """A heartbeat keyed on someone else's payload session id."""
        hook_liveness.write_heartbeat(self.smm_dir, session_id=self.FOREIGN, now=at)

    def _read_without_an_id(self, at: float) -> hook_liveness.Liveness:
        """The shell reader's position: no payload, no session-id variables."""
        with patch.dict(os.environ, _env()):
            return hook_liveness.check_liveness(self.smm_dir, now=at)


class TestAForeignHeartbeatIsNotOurLiveness(_ReadRepairCase):
    """The absent-marker borrow.

    Nothing of ours on disk plus something fresh of theirs used to read live.
    """

    def test_an_id_less_reader_refuses_a_foreign_fresh_heartbeat(self):
        self._foreign_heartbeat(self.NOW)
        result = self._read_without_an_id(self.NOW + 60)
        self.assertFalse(result.live, result.reason)

    def test_the_refusal_is_a_determined_verdict_not_an_undetermined_one(self):
        """The scan answered: no heartbeat this reader can name exists.

        Undetermined is for a check that could not see (a corrupt marker, an
        unresolvable identity); this one saw, and the answer is no. The CLI
        spends a different exit code on each, so the split is observable.
        """
        self._foreign_heartbeat(self.NOW)
        result = self._read_without_an_id(self.NOW + 60)
        self.assertFalse(result.live, result.reason)
        self.assertNotIn(result.code, hook_liveness.UNDETERMINED_CODES)

    def test_the_refusal_does_not_claim_nothing_was_ever_recorded(self):
        """This path newly refuses sessions that used to pass, so its message
        is the entire support surface — and the absent-path text is FALSE
        here, with foreign markers sitting right there on disk."""
        self._foreign_heartbeat(self.NOW)
        borrowed = self._read_without_an_id(self.NOW + 60)
        with patch.dict(os.environ, _env()):
            nothing_at_all = hook_liveness.check_liveness(
                Path(self.smm_dir) / "nowhere", now=self.NOW + 60
            )
        self.assertIn("addressable", borrowed.reason)
        self.assertNotIn("has been recorded", borrowed.reason)
        self.assertNotEqual(borrowed.reason, nothing_at_all.reason)

    def test_it_says_both_why_it_cannot_look_and_what_it_did_see(self):
        """Naming only one half sends the operator after the wrong fix: a
        missing session id and a runtime that never loaded here are different
        problems, and from this position they cannot be told apart."""
        self._foreign_heartbeat(self.NOW)
        reason = self._read_without_an_id(self.NOW + 60).reason
        self.assertIn("no session id", reason)
        self.assertIn("another session", reason)

    def test_an_empty_smm_still_reports_that_nothing_has_run(self):
        """The other half of the split: with no marker of any kind the old
        diagnosis is the true one and must survive the new branch."""
        result = self._read_without_an_id(self.NOW)
        self.assertFalse(result.live)
        self.assertEqual(result.code, hook_liveness.CODE_NO_MARKER)
        self.assertIn("not loaded", result.reason)


class TestAStaleMarkerOfOurOwnIsTheLastWord(_ReadRepairCase):
    """The stale-path copy of the same borrow.

    An id-less host DOES own a heartbeat — the unsuffixed shared marker it
    writes and reads itself. When that one ages out, the runtime stopped
    partway through the session, and a fresh sibling from a session we are
    not was accepted as a reason to keep reporting live.
    """

    STALE = hook_liveness.STALE_AFTER_SECONDS

    def _our_shared_heartbeat(self, at: float) -> None:
        """The heartbeat an id-less host writes for itself: no suffix."""
        with patch.dict(os.environ, _env()):
            hook_liveness.write_heartbeat(self.smm_dir, now=at)

    def test_a_fresh_foreign_heartbeat_does_not_revive_our_stale_one(self):
        self._our_shared_heartbeat(self.NOW)
        self._foreign_heartbeat(self.NOW + self.STALE)
        result = self._read_without_an_id(self.NOW + self.STALE + 60)
        self.assertFalse(result.live, result.reason)

    def test_the_verdict_keeps_the_staleness_diagnosis(self):
        """Refusing is half of it. "Our runtime stopped partway through" is a
        different fix from "no heartbeat we can name exists", and the stale
        marker on disk is what distinguishes them."""
        self._our_shared_heartbeat(self.NOW)
        self._foreign_heartbeat(self.NOW + self.STALE)
        result = self._read_without_an_id(self.NOW + self.STALE + 60)
        self.assertEqual(result.code, hook_liveness.CODE_STALE)
        self.assertIn("stopped", result.reason)


if __name__ == "__main__":
    unittest.main()
