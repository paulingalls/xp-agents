#!/usr/bin/env python3
"""What the observer is sharing, and with whom.

Split from `test_commit_observer.py` when this story's rewrite cases pushed it
past its recorded 450-line sub-cap. Cohesive rather than arbitrary: the SMM is
shared across every checkout and every session, so the observer's record is
addressed by MORE THAN ONE writer. Both classes here are about that, and
neither is about what the observer records from a range it owns alone.

  * `TestMarkerKeying` — the record is keyed on the CHECKOUT. Shared across
    worktrees it would read as an unexplained jump in every checkout but the
    writer's, and then be declined by the range cap forever.
  * `TestTwoObserversSharingACheckout` — two PROCESSES in one checkout,
    serialised by the observer's own lock, plus what that lock still does not
    close.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _append_impl
import _common
import commit_observer
import markers
from _observer_case import _ObserverCase
from conftest import make_event
from event_schema import EVENT_TYPE_COMMIT


class TestMarkerKeying(_ObserverCase):
    """The SMM is shared across worktrees, so one shared record would read as
    an unexplained jump in every checkout but the one that wrote it."""

    def test_the_marker_is_keyed_on_the_checkout_not_the_session(self):
        self.seed_observer()
        self.assertIsNotNone(self.marker())
        self.assertIsNone(
            markers.marker_read(
                self.smm_dir, markers.LAST_SEEN_HEAD, "worktree-story-999"
            )
        )

    def test_another_checkouts_head_is_not_read_as_this_ones(self):
        markers.marker_write(
            self.smm_dir,
            markers.LAST_SEEN_HEAD,
            {"head": "0" * 40},
            "worktree-story-999",
        )
        self.assertIsNone(
            commit_observer.read_last_seen_head(self.smm_dir, str(self.repo))
        )


class TestTwoObserversSharingACheckout(_ObserverCase):
    """AC3. `observe()` runs on every non-commit Bash, so two hooks in one
    checkout can reach the same unrecorded commit at the same time.

    WHAT THESE PROVE, AND WHAT THEY DO NOT. They prove the RE-CHECK under the
    lock: the dedup no longer rests on a snapshot taken before the append, so a
    commit another observer recorded in the window is seen and skipped. That is
    the part that makes the fix work.

    They do NOT prove mutual exclusion between two OS processes. `flock`'s
    SIGALRM timeout only arms on the main thread, so a threaded test cannot
    exercise the real primitive at all, and a two-process test belongs in
    tests/integration/. Claiming the stronger property from this evidence would
    be exactly the overclaim the previous story spent four increments removing.
    """

    def _observe_directly(self) -> None:
        """Straight into the module, not through `run_hook`: the patch below
        wraps a function the surrounding hook pipeline also calls, and the
        window being modelled is `_reconcile`'s own."""
        commit_observer.observe(self.smm_dir, "main", str(self.repo))

    def test_a_commit_recorded_after_the_first_read_is_not_duplicated(self):
        """The real race window. Today's check reads a snapshot taken BEFORE
        the append, so a competitor landing in between is invisible to it."""
        self.seed_observer()
        landed = self.commit("feat: x")
        real = _common.load_events_with_resolutions
        planted = []

        def competing(smm_dir, *args, **kwargs):
            result = real(smm_dir, *args, **kwargs)
            if not planted:
                planted.append(True)
                _common.append_safe(
                    smm_dir,
                    make_event(
                        EVENT_TYPE_COMMIT,
                        content="feat: x",
                        metadata={
                            "commit_hash": landed,
                            "action": "commit_success",
                        },
                    ),
                )
            return result

        with patch("_common.load_events_with_resolutions", side_effect=competing):
            self._observe_directly()
        self.assertEqual(self.recorded_hashes(), [landed])

    def test_a_lock_it_cannot_take_leaves_the_range_open(self):
        """The observer must never raise into the user's Bash call, and must
        not advance the marker over a range it did not record — the next Bash
        retries, and the per-commit dedup makes that resume rather than
        duplicate."""
        self.seed_observer()
        before = self.marker()
        landed = self.commit("feat: x")
        with patch(
            "commit_observer_state.observer_lock",
            side_effect=_append_impl.LockTimeoutError("busy"),
        ):
            self._observe_directly()
        self.assertEqual(self.commit_events(), [])
        self.assertEqual(self.marker(), before)
        self._observe_directly()
        self.assertEqual(self.recorded_hashes(), [landed])


if __name__ == "__main__":
    unittest.main()
