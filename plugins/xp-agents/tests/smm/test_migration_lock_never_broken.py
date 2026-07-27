#!/usr/bin/env python3
"""A migration lock is never broken automatically — only cleared by a human.

Seven attempts tried to make AUTOMATIC stale-lock breaking safe and every one
left the same class reachable: breaking is a read then a delete, no shell
primitive makes that pair indivisible, so a breaker can free a name a live
process claimed in the gap. Two processes then hold, both copy, and the final
`mv` moves one whole tree INSIDE the other.

So the operation stopped being automatic. This suite pins both halves:

* `init.sh` reads a lock's holder and removes the lock on NO path, including the
  one where it loses the claim.
* `migrate_smm_root.py --confirm` clears a lock whose holder is verifiably gone,
  and preserves what it took when it cannot.

The second half is not a proof that two holders are impossible — taking the name
aside frees it. It is a proof that the outcome stays recoverable and loud. What
closed is the AUTOMATIC path: N racers at every session start became one
deliberate command.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import migrate_smm_root as tool
from test_init_migration import _MigrationCase
from test_init_migration_lock import DEAD_PID, _LockFixtures

_TOOL = Path(__file__).parent.parent.parent / "scripts" / "migrate_smm_root.py"


class TestInitNeverRemovesALock(_LockFixtures, _MigrationCase):
    """The resolver's half: read the holder, never remove the lock.

    Two invariants bound every case here. init.sh must never emit empty stdout
    and must never fail — it is the single resolution boundary for every script
    and hook, so an error degrades whole sessions to no-SMM. Declining to
    relocate therefore still has to answer a usable tree.
    """

    def test_a_dead_lock_survives_one_run_unchanged(self):
        home = self._home("survives-one")
        legacy = self._seed_legacy(home)
        lock = self._dead_lock(home)

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertTrue(lock.is_symlink(), "the lock must survive")
        self.assertEqual(os.readlink(lock), DEAD_PID, "and name the same holder")
        self.assertEqual(result.stdout.strip(), str(legacy))
        self.assertFalse(self._new_smm(home).exists(), "nothing may relocate")

    def test_a_dead_lock_still_yields_a_usable_smm(self):
        """Declining is not failing. The answer must be a directory that is
        actually there, with the history in it."""
        home = self._home("survives-usable")
        legacy = self._seed_legacy(home)
        self._dead_lock(home)

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        answered = Path(result.stdout.strip())
        self.assertEqual(answered, legacy)
        self.assertTrue(answered.is_dir(), "the answer must be a real directory")
        self.assertEqual((answered / "events.jsonl").read_text(), '{"e":1}\n')

    def test_eight_racing_runs_leave_a_dead_lock_unchanged(self):
        """The interleaving no read-then-delete break can rule out.

        All eight processes read the SAME dead holder. When breaking was
        automatic, the second breaker's delete landed on the first's fresh claim
        and both went on to copy — and the final rename is a `[[ -d ]]` check one
        syscall from the `mv`, so the loser of THAT buried its whole tree inside
        the live SMM. Nobody breaks and nobody claims now, so two holders have
        nothing to arise from: the observable proof is that no tree moved and no
        temp copy was ever created.

        This case is the end-to-end signal, carried over from
        test_init_migration_lock.py where it used to flake.
        """
        home = self._home("survives-racing")
        legacy = self._seed_legacy(home, events='{"e":"orig"}\n')
        lock = self._dead_lock(home)

        outs = self._parallel_init(home, 8)
        self.assertEqual(outs, [str(legacy)] * 8, "every run must answer legacy")
        self.assertTrue(lock.is_symlink(), "the lock must survive all eight")
        self.assertEqual(os.readlink(lock), DEAD_PID)
        self.assertFalse(self._new_smm(home).exists(), "zero migrations may happen")
        self.assertEqual((legacy / "events.jsonl").read_text(), '{"e":"orig"}\n')
        residue = sorted(p.name for p in lock.parent.iterdir() if p.name != lock.name)
        self.assertEqual(residue, [], f"a run started migrating: {residue}")

    def test_a_directory_shaped_lock_still_excludes_every_racer(self):
        """`ln -s pid dir` puts the link INSIDE dir and SUCCEEDS.

        So the claim cannot rest on `ln -s` alone: against the directory-shaped
        lock an older version wrote, all eight racers would believe they claimed
        it and copy at once — mutual exclusion gone, which is the two-holder
        outcome by another door. Automatic breaking reaped this shape before the
        claim and hid it, so removing the break is what makes it reachable.
        """
        home = self._home("dir-shaped-racing")
        legacy = self._seed_legacy(home, events='{"e":"orig"}\n')
        lock = self._lock_path(home)
        lock.mkdir(parents=True)

        outs = self._parallel_init(home, 8)
        self.assertEqual(outs, [str(legacy)] * 8, "every run must answer legacy")
        self.assertTrue(lock.is_dir(), "the lock must survive")
        self.assertEqual(
            sorted(p.name for p in lock.iterdir()),
            [],
            "a racer claimed by writing its link inside the lock directory",
        )
        self.assertFalse(self._new_smm(home).exists(), "zero migrations may happen")


class TestSupervisedClear(unittest.TestCase):
    """The clear primitive on its own.

    Called in-process rather than through the CLI because the interleavings that
    matter — losing the take, and a claim landing between the take and the
    restore — cannot be produced from outside.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.lock = self.dir / ".migrate.lock"
        self.addCleanup(self._tmp.cleanup)

    def _clear(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = tool.clear_stale_lock(self.lock)
        return code, out.getvalue(), err.getvalue()

    def _residue(self) -> list[str]:
        return sorted(p.name for p in self.dir.iterdir() if p.name != self.lock.name)

    def test_no_lock_is_nothing_to_clear(self):
        code, out, err = self._clear()
        self.assertEqual(code, 0)
        self.assertEqual((out, err), ("", ""))

    def test_a_dead_holders_lock_is_cleared(self):
        self.lock.symlink_to(DEAD_PID)
        code, out, _ = self._clear()
        self.assertEqual(code, 0)
        self.assertFalse(self.lock.is_symlink())
        self.assertIn(DEAD_PID, out)
        self.assertEqual(self._residue(), [], "the taken file must not survive")

    def test_a_live_holders_lock_is_never_cleared(self):
        """No flag reaches this: --force overrides the teammate-liveness signal,
        not lock ownership. A live holder is mid-copy by assumption."""
        self.lock.symlink_to(str(os.getpid()))
        code, _, err = self._clear()
        self.assertEqual(code, 1)
        self.assertTrue(self.lock.is_symlink(), "a live claim must survive")
        self.assertIn("is running", err)
        self.assertEqual(self._residue(), [])

    def test_an_unverifiable_target_is_cleared_and_reported_as_such(self):
        """A lock naming no pid cannot be proven dead — but nothing removes one
        automatically any more, so refusing here would pin the SMM in the
        deletable root with no escape hatch at all. Clear it, and say that
        liveness was never established rather than claiming a corpse."""
        self.lock.symlink_to("not-a-pid")
        code, out, _ = self._clear()
        self.assertEqual(code, 0)
        self.assertFalse(self.lock.is_symlink())
        self.assertIn("no pid", out)

    def test_a_directory_shaped_lock_is_cleared_and_its_contents_named(self):
        """The shape an older init.sh wrote. Nothing removes it automatically
        now, which makes it the one shape that would block relocation forever."""
        self.lock.mkdir()
        (self.lock / "pid").write_text("999999")
        code, out, _ = self._clear()
        self.assertEqual(code, 0)
        self.assertFalse(self.lock.exists())
        self.assertIn("directory containing pid", out)
        self.assertEqual(self._residue(), [])

    def test_the_take_is_single_winner(self):
        """`os.rename` is the atomic step the whole design rests on.

        Of N callers reading the SAME dead holder, exactly one ends up holding
        what was at that name — so there is no second delete left to land on a
        claim somebody made in the meantime. Carried over from the shell
        primitive's suite, which this replaces.

        Counted in the OUTPUT, not in the exit codes: a caller that arrives
        after the winner finds no lock and reports 0 too, because "the name is
        free to claim" is all its caller needs to know.
        """
        for trial in range(20):
            with self.subTest(trial=trial):
                if self.lock.is_symlink():
                    self.lock.unlink()
                self.lock.symlink_to(DEAD_PID)
                out, err = io.StringIO(), io.StringIO()
                with (
                    redirect_stdout(out),
                    redirect_stderr(err),
                    ThreadPoolExecutor(max_workers=8) as pool,
                ):
                    for f in [
                        pool.submit(tool.clear_stale_lock, self.lock) for _ in range(8)
                    ]:
                        f.result()
                cleared = out.getvalue().count("Cleared the migration lock")
                self.assertEqual(cleared, 1, f"expected one clearer: {out.getvalue()}")

    def test_a_claim_that_lands_in_the_gap_is_put_back(self):
        """Taking the name is not verifying what was under it.

        The readlink and the rename are separate syscalls, so a racer can free
        the name and claim it in between. What comes out of the rename is then
        somebody's LIVE claim, and it goes back rather than being deleted.
        """
        self.lock.symlink_to(DEAD_PID)
        live = str(os.getpid())
        real_rename = os.rename

        def claim_then_rename(src, dst):
            os.unlink(src)
            os.symlink(live, src)  # a racer's fresh, live claim
            real_rename(src, dst)

        with mock.patch("os.rename", claim_then_rename):
            code, _, err = self._clear()

        self.assertEqual(code, 1)
        self.assertTrue(self.lock.is_symlink(), "the racer's claim must be restored")
        self.assertEqual(os.readlink(self.lock), live)
        self.assertIn("put back", err)
        self.assertEqual(self._residue(), [])

    def test_a_restore_that_fails_leaves_the_taken_claim_recoverable(self):
        """The residual this design accepts, made survivable.

        Taking the name aside FREES it, so a second racer can occupy it, and
        then the no-clobber restore has nowhere to go. Deleting what we hold is
        what the automatic breaker did — it destroyed a live claim and left two
        migrations running. So it is kept, named, and the refusal says so.
        """
        self.lock.symlink_to(DEAD_PID)
        real_rename = os.rename

        def claim_take_then_claim_again(src, dst):
            os.unlink(src)
            os.symlink("4242", src)  # racer one: what we will take
            real_rename(src, dst)
            os.symlink("5151", src)  # racer two: occupies the freed name

        with mock.patch("os.rename", claim_take_then_claim_again):
            code, _, err = self._clear()

        self.assertNotEqual(code, 0)
        taken = self.dir / f".migrate.lock.clearing.{os.getpid()}"
        self.assertTrue(taken.is_symlink(), "the taken claim must not be deleted")
        self.assertEqual(os.readlink(taken), "4242")
        self.assertEqual(
            os.readlink(self.lock), "5151", "the racer's lock is untouched"
        )
        self.assertIn(str(taken), err)
        self.assertIn("TWO MIGRATIONS MAY NOW BE IN FLIGHT", err)


class TestSupervisedClearEndToEnd(_LockFixtures, _MigrationCase):
    """The whole command: report, clear, relocate — in one invocation."""

    def _tool(self, home: Path, *args: str) -> subprocess.CompletedProcess:
        env = dict(self._test_env)
        env["HOME"] = str(home)
        for name in ("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA", "SMM_DIR"):
            env.pop(name, None)
        return subprocess.run(
            [sys.executable, str(_TOOL), *args],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(self.tmpdir),
            env=env,
        )

    def _dead_lock(self, home: Path) -> Path:
        lock = self._lock_path(home)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.symlink_to(DEAD_PID)
        return lock

    def test_the_report_names_the_lock_and_its_holder(self):
        """A lock nothing removes on its own is invisible until someone looks —
        so the report is the only place a stuck relocation surfaces."""
        home = self._home("report-lock")
        self._seed_legacy(home)
        lock = self._dead_lock(home)

        result = self._tool(home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(lock), result.stdout)
        self.assertIn(f"pid {DEAD_PID}", result.stdout)
        self.assertIn("not running", result.stdout)
        self.assertTrue(lock.is_symlink(), "a report must not clear anything")

    def test_confirm_clears_a_dead_lock_and_relocates_in_one_invocation(self):
        """The command has no next run to defer to.

        A session that meets a dead lock now just declines and answers legacy,
        forever, so this is the only thing that gets the SMM out of the root
        `claude plugin uninstall` deletes.
        """
        home = self._home("clear-and-move")
        legacy = self._seed_legacy(home)
        lock = self._dead_lock(home)

        result = self._tool(home, "--confirm")
        self.assertEqual(result.returncode, 0, result.stderr)
        new = self._new_smm(home)
        self.assertIn(f"Relocated to {new}", result.stdout)
        self.assertEqual((new / "events.jsonl").read_text(), '{"e":1}\n')
        self.assertFalse(lock.is_symlink(), "the cleared lock must not survive")
        self.assertTrue(legacy.exists())

    def test_confirm_force_refuses_to_clear_a_live_holder(self):
        home = self._home("live-holder")
        self._seed_legacy(home)
        lock, holder = self._hold_lock(home)

        result = self._tool(home, "--confirm", "--force")
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"(pid {holder.pid}) is running", result.stderr)
        self.assertTrue(lock.is_symlink(), "a live claim must survive --force")
        self.assertEqual(os.readlink(lock), str(holder.pid))
        self.assertFalse(self._new_smm(home).exists())

    def test_confirm_clears_a_directory_shaped_lock_and_says_what_it_removed(self):
        home = self._home("dir-lock")
        self._seed_legacy(home)
        lock = self._lock_path(home)
        lock.mkdir(parents=True)
        (lock / "pid").write_text(DEAD_PID)

        result = self._tool(home, "--confirm")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("directory containing pid", result.stdout)
        self.assertFalse(lock.exists())
        self.assertEqual(
            (self._new_smm(home) / "events.jsonl").read_text(), '{"e":1}\n'
        )


if __name__ == "__main__":
    unittest.main()
