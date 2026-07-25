#!/usr/bin/env python3
"""Concurrency tests for the stale-migration-lock break primitive.

Try `retro-try-migration-lock-test`: four sequential patches to this lock
each introduced a new defect, so the invariant gets a test before the code
is touched again.

The invariant: **breaking is single-winner.** A dead lock is broken by at
most one racer, and a breaker never deletes a claim it did not verify as a
corpse. Without that, the interleaving is reachable — P1 verifies the
holder is dead, P2 frees the name first, P3 claims it and is genuinely
live, and P1's delete lands on P3's live claim. Two holders then migrate
at once, and the final rename is a check one syscall from the `mv`, so the
loser buries a whole duplicate tree inside the live SMM.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_BREAK_SH = (
    Path(__file__).parent.parent.parent / "smm" / "break_stale_lock.sh"
)

# Exit codes the helper promises its one caller (init.sh).
BROKE = 0
HELD = 1
ABSENT = 2

# A pid that cannot be live. Above the platform maximum on both targets.
DEAD_PID = "999999"


class _LockCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.lock = self.dir / ".migrate.lock"
        self.addCleanup(self._tmp.cleanup)

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(_BREAK_SH), str(self.lock)],
            capture_output=True,
            text=True,
        )

    def _residue(self) -> list[str]:
        return sorted(
            p.name for p in self.dir.iterdir() if p.name != ".migrate.lock"
        )


class TestBreakSingleOutcomes(_LockCase):
    def test_no_lock_reports_absent(self):
        self.assertEqual(self._run().returncode, ABSENT)

    def test_dead_holder_is_broken_and_the_name_freed(self):
        self.lock.symlink_to(DEAD_PID)
        self.assertEqual(self._run().returncode, BROKE)
        self.assertFalse(self.lock.is_symlink())

    def test_live_holder_is_left_alone(self):
        self.lock.symlink_to(str(os.getpid()))
        self.assertEqual(self._run().returncode, HELD)
        self.assertTrue(self.lock.is_symlink(), "a live claim must survive")

    def test_a_non_numeric_target_is_treated_as_breakable(self):
        """No holder we can verify is a holder we must yield to forever —
        an unbreakable lock would pin the SMM in the deletable root."""
        self.lock.symlink_to("not-a-pid")
        self.assertEqual(self._run().returncode, BROKE)
        self.assertFalse(self.lock.is_symlink())

    def test_a_directory_shaped_lock_from_an_older_version_is_reaped(self):
        self.lock.mkdir()
        self.assertEqual(self._run().returncode, BROKE)
        self.assertFalse(self.lock.exists())

    def test_breaking_leaves_no_residue(self):
        self.lock.symlink_to(DEAD_PID)
        self._run()
        self.assertEqual(self._residue(), [])


class TestBreakIsSingleWinner(_LockCase):
    """The property four patches failed to establish.

    With an unconditional `rm`, every racer that read the same dead holder
    deletes the name — including whatever a third process has claimed in
    the meantime. Taking the name by rename makes exactly one racer the
    breaker, so there is no second delete to land on a live claim.
    """

    RACERS = 8
    TRIALS = 40

    def _race(self) -> list[int]:
        with ThreadPoolExecutor(max_workers=self.RACERS) as pool:
            return [f.result().returncode for f in [
                pool.submit(self._run) for _ in range(self.RACERS)
            ]]

    def test_exactly_one_racer_breaks_a_dead_lock(self):
        for trial in range(self.TRIALS):
            with self.subTest(trial=trial):
                if self.lock.is_symlink():
                    self.lock.unlink()
                self.lock.symlink_to(DEAD_PID)
                codes = self._race()
                self.assertEqual(
                    codes.count(BROKE),
                    1,
                    f"expected exactly one breaker, got {codes.count(BROKE)}",
                )

    def test_a_racer_never_deletes_a_live_claim(self):
        """The end-state the whole primitive exists to protect.

        Racers all read the dead holder; a live claim is planted while they
        run. Whoever loses the break must not delete it.
        """
        for trial in range(self.TRIALS):
            with self.subTest(trial=trial):
                for p in self.dir.iterdir():
                    p.unlink()
                self.lock.symlink_to(DEAD_PID)
                live = str(os.getpid())
                with ThreadPoolExecutor(max_workers=self.RACERS + 1) as pool:
                    futures = [
                        pool.submit(self._run) for _ in range(self.RACERS)
                    ]
                    pool.submit(self._claim_when_free, live)
                    for f in futures:
                        f.result()
                if self.lock.is_symlink():
                    self.assertIn(
                        os.readlink(self.lock),
                        {DEAD_PID, live},
                        "the name holds something nobody planted",
                    )

    def _claim_when_free(self, pid: str) -> None:
        for _ in range(200):
            try:
                os.symlink(pid, self.lock)
                return
            except FileExistsError:
                continue


if __name__ == "__main__":
    unittest.main()
