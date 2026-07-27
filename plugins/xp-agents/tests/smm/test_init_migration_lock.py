#!/usr/bin/env python3
"""Concurrency and crash residue in init.sh's legacy-SMM relocation.

Split from test_init_migration.py (500-line cap): that file covers WHAT
relocation does — copy, decline, override — while this one covers what happens
when two processes reach it at once, or when a previous one died partway.

The property under test throughout is that the loser of a race must never be
able to damage the winner, and that a process which cannot migrate must still
resolve SOMETHING: empty stdout from init.sh degrades the whole session to
no-SMM.

The lock's NAME and SHAPE are pinned here too, against the reader in
`scripts/migrate_smm_root.py`: this is where the helper that encodes them lives,
and every other case fabricates the lock rather than watching init.sh claim one.
"""

import os
import shutil
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import migrate_smm_root as tool
from test_init_migration import _MigrationCase

# A pid that cannot be live: above the maximum on both supported platforms.
DEAD_PID = "999999"


class _LockCase(_MigrationCase):
    """``_MigrationCase`` plus lock scaffolding.

    A base case rather than a mixin: every helper here needs the temp HOME, the
    project id and the init.sh runner that ``_MigrationCase`` provides, and
    subclassing it is what lets a type checker see them without a second copy of
    the TYPE_CHECKING mixin shim (`tests/_test_typing._MixinBase`, pinned to a
    single definition). Shared with ``test_migration_lock_never_broken.py``.
    """

    def _lock_path(self, home: Path) -> Path:
        """Where init.sh claims the migration lock for this HOME's new root."""
        return home / ".xp-agents" / "data" / self._project_id() / ".migrate.lock"

    def _dead_lock(self, home: Path) -> Path:
        """A lock in the shape init.sh claims, naming a holder that is gone."""
        lock = self._lock_path(home)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.symlink_to(DEAD_PID)
        return lock

    def _parallel_init(self, home: Path, n: int) -> list[str]:
        """Run n init.sh processes at once against `home`; return their answers."""
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
            for _ in range(n)
        ]
        outs = []
        for p in procs:
            out, err = p.communicate(timeout=60)
            self.assertEqual(p.returncode, 0, f"init.sh failed: {err}")
            outs.append(out.strip())
        return outs

    def _sleep_shim(self, *, fractional_ok: bool) -> tuple[Path, Path]:
        """A PATH-shimmed `sleep` that records its argument instead of waiting.

        Returns (bin_dir, log). ``fractional_ok=False`` models the platforms
        this loop's whole-second fallback exists for: a `sleep` that rejects a
        fractional argument. The dir is keyed on the test method as well as the
        flag, because the log APPENDS — two cases sharing one would sum each
        other's ticks.
        """
        which = "frac" if fractional_ok else "whole"
        bin_dir = self.tmpdir / f"shim-{self._testMethodName}-{which}"
        bin_dir.mkdir(exist_ok=True)
        log = bin_dir / "sleep.log"
        reject = "" if fractional_ok else 'case "$1" in *.*) exit 1;; esac\n'
        shim = bin_dir / "sleep"
        shim.write_text(f'#!/bin/bash\n{reject}printf "%s\\n" "$1" >>"{log}"\n')
        shim.chmod(0o755)
        return bin_dir, log

    def _slept_seconds(
        self, home: Path, *, fractional_ok: bool = True
    ) -> tuple[float, subprocess.CompletedProcess]:
        """Run init.sh with a recording `sleep`; return (seconds, result).

        Zero seconds means it never waited at all, which is a real answer and
        not a missing log: a path that short-circuits must be able to prove it.
        """
        bin_dir, log = self._sleep_shim(fractional_ok=fractional_ok)
        result = self._run_init(
            extra_env={
                "HOME": str(home),
                "PATH": f"{bin_dir}:{self._test_env['PATH']}",
            },
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        if not log.exists():
            return 0.0, result
        return sum(float(line) for line in log.read_text().split()), result

    def _hold_lock(self, home: Path) -> tuple[Path, subprocess.Popen]:
        """Claim the lock for a process that is genuinely alive."""
        holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        lock = self._lock_path(home)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.symlink_to(str(holder.pid))
        return lock, holder


class TestCrashResidue(_LockCase):
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

    def _assert_lock_survives_and_nothing_migrates(
        self, home: Path, lock: Path
    ) -> None:
        """A dead lock is residue, and a resolver still does not remove it.

        Breaking one is a read then a delete, and no shell primitive makes that
        pair indivisible: two processes read the SAME dead holder, and the
        second's delete lands on the first's fresh live claim — two "holders",
        both copying, both racing the final rename that buries one whole tree
        inside the other. Renaming the lock aside instead of deleting it does not
        help either; `mv` acts on the NAME, so it frees a live claim exactly as
        `rm` does.

        So nothing automatic touches it. Every run declines and answers legacy —
        including the SECOND one, which is the part that changed: this used to
        break on run one and relocate on run two. Clearing a dead lock is now
        `scripts/migrate_smm_root.py --confirm`, supervised and one-shot.

        The cost is recorded as debt rather than hidden: until somebody runs that
        command, a crashed relocation's lock blocks the automatic path.
        """
        legacy = home / ".claude" / "plugins" / "data" / "xp-agents-xp-agents"
        legacy = legacy / self._project_id() / "smm"

        for run in ("first", "second"):
            result = self._migrate(home)
            self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
            self.assertEqual(
                result.stdout.strip(),
                str(legacy),
                f"the {run} run must decline and answer legacy",
            )
            self.assertFalse(
                self._new_smm(home).exists(),
                f"the {run} run must not relocate anything",
            )
            self.assertTrue(
                lock.is_symlink() or lock.exists(),
                f"the {run} run removed the lock",
            )

    def test_a_dead_holder_lock_is_not_broken(self):
        """Directory-shaped, which is what an OLDER version of this script wrote.

        It names no holder anything can verify — and is still left alone, because
        reaping it is the same read-then-delete. This is precisely the shape the
        supervised clear exists to remove, since nothing else ever will.
        """
        home = self._home("deadlock")
        self._seed_legacy(home)
        lock = self._lock_path(home)
        lock.mkdir(parents=True)
        # PID 1 is alive but is not us; use an implausible one that is not.
        (lock / "pid").write_text(DEAD_PID)

        self._assert_lock_survives_and_nothing_migrates(home, lock)
        self.assertTrue(lock.is_dir(), "the lock must survive in its own shape")
        self.assertEqual((lock / "pid").read_text(), DEAD_PID, "contents and all")

    def test_a_lock_naming_a_dead_holder_is_not_broken(self):
        """Same property, in the shape this script actually claims the lock in.

        The holder is published as the link TARGET, by the same syscall that
        claims the name — so a lock is never observable without its holder, and
        a racer can never mistake a live claim for a stale one. Reading that
        holder is all the resolver does with it.
        """
        home = self._home("dead-holder")
        self._seed_legacy(home)
        lock = self._dead_lock(home)

        self._assert_lock_survives_and_nothing_migrates(home, lock)
        self.assertEqual(os.readlink(lock), DEAD_PID, "unchanged, holder and all")

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


class TestMigrationLockYields(_LockCase):
    """What a process that LOSES the lock resolves to.

    Not the legacy tree if it can be helped: the winner's last whole-tree
    re-sync happens BEFORE its rename, so every event a loser appends to legacy
    after that instant is absent from the migrated SMM and invisible to every
    later session — the session that performed the upgrade would show a gap.
    """

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

    def _wait_budget_seconds(self, *, fractional_ok: bool) -> float:
        """Total wall-clock seconds a lock loser would have slept."""
        home = self._home(f"budget-{'frac' if fractional_ok else 'whole'}")
        legacy = self._seed_legacy(home)
        self._hold_lock(home)

        slept, result = self._slept_seconds(home, fractional_ok=fractional_ok)
        self.assertEqual(result.stdout.strip(), str(legacy))
        self.assertGreater(slept, 0, "the loser must have entered the wait loop")
        return slept

    def test_the_wait_is_bounded_in_seconds_not_in_ticks(self):
        """The budget must not depend on whether `sleep` takes a fraction.

        A fixed tick COUNT made it depend on exactly that: the loop sleeps 0.1s
        where fractional sleep works and a whole second where it does not, so
        the same count was 3 seconds on one platform and 30 on another — and 30
        is precisely the whole budget the SessionStart hook gives init.sh. On
        such a platform a lock loser timed out with CERTAINTY and the session
        got no SMM at all. Same wall clock either way, coarser polling.
        """
        fine = self._wait_budget_seconds(fractional_ok=True)
        coarse = self._wait_budget_seconds(fractional_ok=False)
        self.assertAlmostEqual(fine, coarse, places=6)
        self.assertLessEqual(
            coarse,
            10.0,
            "the wait must finish comfortably inside session_start's 30s budget",
        )

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


class TestMigrationConcurrency(_LockCase):
    """Racing runs against a FREE lock name.

    The dead-lock-in-parallel case moved to
    ``test_migration_lock_never_broken.py``, where the invariant it now pins
    lives: nothing breaks the lock, so no run migrates at all. Keeping a copy
    here would have been a verbatim duplicate of it.
    """

    def test_parallel_invocations_produce_exactly_one_migrated_smm(self):
        """N processes hit the migrate branch at once at every session start —
        SessionStart, several skill preloads and appends fire near-together,
        and teammates run their own. This is the test that justifies the lock;
        reasoning about it is not enough.
        """
        home = self._home("parallel")
        legacy = self._seed_legacy(home, events='{"e":"orig"}\n')

        outs = self._parallel_init(home, 8)
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


class TestTheLockNameAndShapeAreOneContract(_LockCase):
    """Two files now have to agree on the lock, so pin BOTH sides of it.

    init.sh writes the claim and the tool reads it. Nothing else reconciles
    them: if init.sh moved the name, or claimed a directory instead of a symlink
    naming its pid, the tool would find "residue from an older version" at the
    name a LIVE migration holds and clear it — and every other case in these two
    lock suites would still pass, because they all fabricate the lock themselves.
    """

    def _cp_shim(self, lock: Path) -> tuple[Path, Path]:
        """A PATH-shimmed `cp` that records the lock's shape, then really copies.

        The claim exists only between the `ln -s` and the release, and the copy
        is what happens in between — so shimming `cp` is the one way to observe
        it from outside. The real `cp` is resolved HERE, before the shim dir is
        on PATH, so the shim cannot find itself.
        """
        real_cp = shutil.which("cp")
        self.assertIsNotNone(real_cp, "no cp on PATH to shim")
        bin_dir = self.tmpdir / f"cpshim-{self._testMethodName}"
        bin_dir.mkdir(exist_ok=True)
        log = bin_dir / "shape.log"
        shim = bin_dir / "cp"
        shim.write_text(
            "#!/bin/bash\n"
            f'if [[ -L "{lock}" ]]; then\n'
            f'    printf "symlink %s\\n" "$(readlink "{lock}")" >>"{log}"\n'
            f'elif [[ -d "{lock}" ]]; then printf "dir\\n" >>"{log}"\n'
            f'elif [[ -e "{lock}" ]]; then printf "file\\n" >>"{log}"\n'
            f'else printf "absent\\n" >>"{log}"\n'
            "fi\n"
            f'exec "{real_cp}" "$@"\n'
        )
        shim.chmod(0o755)
        return bin_dir, log

    def test_the_claim_init_sh_writes_is_the_one_the_tool_reads(self):
        home = self._home("lock-contract")
        legacy = self._seed_legacy(home)
        lock = self._lock_path(home)
        bin_dir, log = self._cp_shim(lock)

        result = self._run_init(
            extra_env={
                "HOME": str(home),
                "PATH": f"{bin_dir}:{self._test_env['PATH']}",
            },
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(
            result.stdout.strip(),
            str(self._new_smm(home)),
            "the migration must actually have run for the claim to be observed",
        )

        shapes = log.read_text().splitlines() if log.exists() else []
        self.assertTrue(shapes, "the copy never ran, so nothing observed the claim")
        for shape in shapes:
            kind, _, target = shape.partition(" ")
            self.assertEqual(kind, "symlink", f"the claim was not a symlink: {shape}")
            # A pid, in the form `holder_state` and init.sh's `^[0-9]+$` agree on.
            self.assertTrue(
                target.isascii() and target.isdigit(),
                f"the claim must name a pid, not {target!r}",
            )
            self.assertIsNotNone(
                tool.holder_state(target),
                f"the tool must be able to verify liveness of {target!r}",
            )

        # And the tool computes that same name from where the SMM was found.
        env = {k: v for k, v in os.environ.items() if k != "XP_AGENTS_DATA"}
        env["HOME"] = str(home)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(tool.lock_path_for(legacy), lock)


if __name__ == "__main__":
    unittest.main()
