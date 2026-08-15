#!/usr/bin/env python3
"""Tests for marker_claim.claim — the exclusive, expiring claim.

The failure this primitive exists to prevent was measured, not imagined: four
parallel firings each read the marker absent and each ran the work. That is
check-then-act, and no amount of atomic WRITING fixes it — the gap is between
the check and the write, so the claim has to be the create itself.

The race test below therefore ships with a control. "Exactly one winner" is a
result a broken implementation can produce by luck on a quiet machine, so the
same harness is also run against a deliberately check-then-act claimant, and
that one must let more than one through. Without the control the test proves
the harness is quiet, not that the claim is atomic.
"""

import os
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import marker_claim
import markers
from conftest import _SMMTestCase

_CLAIM = markers.MarkerDef(".test-claim", "text")
_RACERS = 16


class TestClaimIsExclusive(_SMMTestCase):
    def test_the_first_claimant_wins_and_the_second_is_refused(self):
        self.assertTrue(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))
        self.assertFalse(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))

    def test_the_claim_leaves_a_file_behind(self):
        marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60)
        self.assertTrue(markers.marker_path(self.smm_dir, _CLAIM).is_file())

    def test_a_consumed_claim_can_be_retaken(self):
        self.assertTrue(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))
        markers.marker_consume(self.smm_dir, _CLAIM)
        self.assertTrue(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))


class TestClaimExpires(_SMMTestCase):
    """The lifetime is the whole design.

    A claim that outlives its invocation silently starves the NEXT one — the
    same class of quiet failure the claim exists to prevent, arriving from the
    other side. So expiry is pinned in both directions.
    """

    def test_a_claim_older_than_the_window_is_retaken(self):
        self.assertTrue(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))
        path = markers.marker_path(self.smm_dir, _CLAIM)
        stale = time.time() - 120
        os.utime(path, (stale, stale))
        self.assertTrue(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))

    def test_a_claim_inside_the_window_still_holds(self):
        self.assertTrue(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))
        path = markers.marker_path(self.smm_dir, _CLAIM)
        recent = time.time() - 5
        os.utime(path, (recent, recent))
        self.assertFalse(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))

    def test_retaking_a_stale_claim_refreshes_its_age(self):
        """Otherwise the reclaimed marker is instantly stale again and every
        subsequent claimant wins too — an expiring claim that expires always."""
        marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60)
        path = markers.marker_path(self.smm_dir, _CLAIM)
        stale = time.time() - 120
        os.utime(path, (stale, stale))
        self.assertTrue(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))
        self.assertFalse(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))


class TestClaimRefusesASymlink(_SMMTestCase):
    """Same posture as `marker_exists`, which reports a symlinked marker absent.

    A claim that followed the link would write through it, and one that deleted
    it on staleness would remove a file it never owned.
    """

    def test_a_symlinked_claim_path_is_refused(self):
        target = Path(self.smm_dir) / "elsewhere"
        target.write_text("not ours", encoding="utf-8")
        markers.marker_path(self.smm_dir, _CLAIM).symlink_to(target)

        self.assertFalse(marker_claim.claim(self.smm_dir, _CLAIM, ttl_seconds=60))
        self.assertEqual(target.read_text(encoding="utf-8"), "not ours")


def _race(claimant, smm_dir: Path) -> int:
    """Run `claimant` from `_RACERS` threads released together; count winners.

    A barrier rather than a plain thread start: without it the threads trickle
    in and the first one is usually finished before the last begins, which is
    the shape that lets a check-then-act claim pass a race test.
    """
    barrier = threading.Barrier(_RACERS)
    wins: list[bool] = []
    lock = threading.Lock()

    def attempt():
        barrier.wait(timeout=30)
        won = claimant(smm_dir)
        with lock:
            wins.append(won)

    threads = [threading.Thread(target=attempt) for _ in range(_RACERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        # Bounded: an unbounded join would hang the whole suite if one
        # racer died before reaching the barrier, and a hanging test is
        # worse than a failing one.
        thread.join(timeout=30)
    return sum(wins)


def _check_then_act(smm_dir: Path) -> bool:
    """The measured bug, reproduced: look, then write.

    The sleep does not invent the race — it widens a window that is genuinely
    there. In the run this primitive exists to fix, the gap was filled by four
    separate PROCESSES being scheduled between the read and the write.
    """
    if markers.marker_exists(smm_dir, _CLAIM):
        return False
    time.sleep(0.01)
    markers.marker_write(smm_dir, _CLAIM, "held")
    return True


class TestClaimUnderRealConcurrency(_SMMTestCase):
    def test_exactly_one_of_many_racing_claimants_wins(self):
        winners = _race(
            lambda smm: marker_claim.claim(smm, _CLAIM, ttl_seconds=60),
            self.smm_dir,
        )
        self.assertEqual(winners, 1, f"{winners} claimants won the same claim")

    def test_the_harness_would_catch_a_check_then_act_claim(self):
        """The control. If this passes with one winner, the test above proves
        nothing about atomicity — only that the machine was quiet."""
        winners = _race(_check_then_act, self.smm_dir)
        self.assertGreater(
            winners,
            1,
            "the check-then-act control won only once, so the race harness "
            "cannot distinguish an atomic claim from a broken one",
        )


if __name__ == "__main__":
    unittest.main()
