#!/usr/bin/env python3
"""Concurrency and crash residue in init.sh's legacy-SMM relocation.

Split from test_init_migration.py (500-line cap): that file covers WHAT
relocation does — copy, decline, override — while this one covers what happens
when two processes reach it at once, or when a previous one died partway.

The property under test throughout is that the loser of a race must never be
able to damage the winner, and that a process which cannot migrate must still
resolve SOMETHING: empty stdout from init.sh degrades the whole session to
no-SMM.
"""

import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from test_init_migration import _MigrationCase


class TestCrashResidue(_MigrationCase):
    """A partial migration must never read as a complete one."""

    def test_bare_project_id_dir_does_not_read_as_migrated(self):
        home = self._home("bare")
        legacy = self._seed_legacy(home)
        # What a crash between mkdir and rename leaves behind.
        (home / ".xp-agents" / "data" / self._project_id()).mkdir(parents=True)

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(self._new_smm(home)))
        new = self._new_smm(home)
        self.assertEqual((new / "events.jsonl").read_text(), '{"e":1}\n')
        self.assertTrue(legacy.exists())

    def test_leftover_temp_dir_does_not_block_migration(self):
        home = self._home("temp")
        self._seed_legacy(home)
        project_dir = home / ".xp-agents" / "data" / self._project_id()
        project_dir.mkdir(parents=True)
        stale = project_dir / ".migrating.99999.stale"
        stale.mkdir()
        (stale / "half-copied.json").write_text("{}")

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(self._new_smm(home)))
        new = self._new_smm(home)
        self.assertEqual((new / "events.jsonl").read_text(), '{"e":1}\n')
        # The temp name is pid-derived, so a stale one never collides and
        # migration would succeed even if it were never cleaned up. Assert the
        # cleanup itself, or this test passes with the cleanup deleted.
        self.assertFalse(stale.exists(), "crashed-run residue must be reaped")

    def test_dead_holder_lock_is_broken(self):
        """A lock whose holder is gone must not deadlock the plugin forever.

        Directory-shaped, which is what an OLDER version of this script wrote:
        it names no holder the current script can verify, so it is residue and
        must be reaped rather than yielded to forever.
        """
        home = self._home("deadlock")
        self._seed_legacy(home)
        lock = home / ".xp-agents" / "data" / self._project_id() / ".migrate.lock"
        lock.mkdir(parents=True)
        # PID 1 is alive but is not us; use an implausible one that is not.
        (lock / "pid").write_text("999999")

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(self._new_smm(home)))
        self.assertFalse(lock.exists(), "a broken lock must be cleaned up")

    def test_lock_naming_a_dead_holder_is_broken(self):
        """Same property, in the shape this script actually claims the lock in.

        The holder is published as the link TARGET, by the same syscall that
        claims the name — so a lock is never observable without its holder, and
        a racer can never mistake a live claim for a stale one.
        """
        home = self._home("dead-holder")
        self._seed_legacy(home)
        lock = home / ".xp-agents" / "data" / self._project_id() / ".migrate.lock"
        lock.parent.mkdir(parents=True)
        lock.symlink_to("999999")

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(self._new_smm(home)))
        self.assertFalse(lock.is_symlink(), "a broken lock must be cleaned up")

    def test_a_live_runs_in_flight_copy_is_never_reaped(self):
        """Residue is reaped by LIVENESS, not by "it is not mine".

        An unconditional `rm -rf .migrating.*` deletes a copy another process is
        still writing. That process then renames a truncated tree into place,
        and because completion is marked by the destination existing, every
        later session reads the truncation as the whole SMM.
        """
        home = self._home("live-temp")
        self._seed_legacy(home)
        project_dir = home / ".xp-agents" / "data" / self._project_id()
        project_dir.mkdir(parents=True)
        live = project_dir / f".migrating.{os.getpid()}"
        live.mkdir()
        (live / "half-copied.json").write_text("{}")

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertTrue(
            (live / "half-copied.json").exists(),
            "a live run's in-flight copy must survive another run's reap",
        )


class TestMigrationLockYields(_MigrationCase):
    """What a process that LOSES the lock resolves to.

    Not the legacy tree if it can be helped: the winner's last whole-tree
    re-sync happens BEFORE its rename, so every event a loser appends to legacy
    after that instant is absent from the migrated SMM and invisible to every
    later session — the session that performed the upgrade would show a gap.
    """

    def _hold_lock(self, home: Path) -> tuple[Path, subprocess.Popen]:
        """Claim the lock for a process that is genuinely alive."""
        holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        lock = home / ".xp-agents" / "data" / self._project_id() / ".migrate.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.symlink_to(str(holder.pid))
        return lock, holder

    def test_a_live_holders_lock_is_not_broken(self):
        home = self._home("live-lock")
        legacy = self._seed_legacy(home)
        lock, _ = self._hold_lock(home)

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertTrue(lock.is_symlink(), "a live holder's lock must survive")
        # Nothing else finished the migration, so legacy is the only answer left.
        self.assertEqual(result.stdout.strip(), str(legacy))
        self.assertFalse(self._new_smm(home).exists())

    def test_waits_for_the_winner_instead_of_taking_the_legacy_tree(self):
        home = self._home("waits")
        self._seed_legacy(home)
        lock, _ = self._hold_lock(home)
        new = self._new_smm(home)

        def winner_finishes():
            new.mkdir(parents=True, exist_ok=True)
            (new / "events.jsonl").write_text('{"e":1}\n')
            lock.unlink()

        timer = threading.Timer(0.5, winner_finishes)
        self.addCleanup(timer.cancel)
        timer.start()

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(
            result.stdout.strip(),
            str(new),
            "a loser must resolve the migrated tree the winner produced",
        )


class TestMigrationConcurrency(_MigrationCase):
    def test_parallel_invocations_produce_exactly_one_migrated_smm(self):
        """N processes hit the migrate branch at once at every session start —
        SessionStart, several skill preloads and appends fire near-together,
        and teammates run their own. This is the test that justifies the lock;
        reasoning about it is not enough.
        """
        home = self._home("parallel")
        legacy = self._seed_legacy(home, events='{"e":"orig"}\n')
        env = dict(self._test_env)
        env["HOME"] = str(home)
        for var in ("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"):
            env.pop(var, None)

        procs = [
            subprocess.Popen(
                [str(self._INIT_SH)],
                cwd=str(self.tmpdir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(8)
        ]
        outs = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, f"init.sh failed: {err}")
            outs.append(out.strip())

        new_smm = self._new_smm(home)
        self.assertTrue(all(o for o in outs), "every invocation must print a path")
        # Each printed either the migrated path or the legacy one it fell back
        # to; none may print anything else, and none may be empty.
        self.assertTrue(
            set(outs) <= {str(new_smm), str(legacy)},
            f"unexpected resolved paths: {set(outs)}",
        )
        self.assertEqual((new_smm / "events.jsonl").read_text(), '{"e":"orig"}\n')
        residue = [
            p.name for p in new_smm.parent.iterdir() if p.name.startswith(".migrat")
        ]
        self.assertEqual(residue, [], f"temp/lock residue left behind: {residue}")
        # INSIDE the SMM too: `mv tmp dst` moves INTO dst when dst exists, so a
        # loser that reached the rename after the winner finished would bury a
        # whole duplicate SMM here rather than fail.
        nested = [p.name for p in new_smm.iterdir() if p.name.startswith(".migrat")]
        self.assertEqual(nested, [], f"a losing migration landed inside: {nested}")


if __name__ == "__main__":
    unittest.main()
