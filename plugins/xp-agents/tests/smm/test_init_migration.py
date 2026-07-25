#!/usr/bin/env python3
"""Tests for init.sh's auto-migration of a legacy SMM to the new data root.

The SMM used to live under ${CLAUDE_PLUGIN_DATA}, which `claude plugin
uninstall` DELETES by default — so a routine uninstall silently destroyed a
project's entire memory. Commit 3 moved the default root and made an existing
SMM merely DISCOVERABLE there; this suite covers actually relocating it.

Two properties dominate every test here:

1. **The source is never deleted.** Migration copies. An interrupted or wrong
   migration therefore loses nothing, and every failure path can fall back to
   reading the legacy tree.
2. **Migration is declined, never forced.** A live teammate has its SMM_DIR
   pinned to an absolute path at spawn and cannot be redirected, so migrating
   out from under one splits the log. Declining is always safe; forcing is not.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from conftest import _TempRepoTestCase


class _MigrationCase(_TempRepoTestCase):
    """Shared scaffolding: a fake HOME whose only SMM is a legacy one."""

    def _home(self, name: str) -> Path:
        home = self.tmpdir / f"home-{name}"
        home.mkdir(parents=True, exist_ok=True)
        return home

    def _project_id(self) -> str:
        probe = self.tmpdir / "probe"
        r = self._run_init(extra_env={"XP_AGENTS_DATA": str(probe)})
        self.assertEqual(r.returncode, 0, f"probe failed: {r.stderr}")
        return Path(r.stdout.strip()).parent.name

    def _seed_legacy(self, home: Path, *, events: str = '{"e":1}\n') -> Path:
        """A populated legacy SMM under the marketplace default for this repo."""
        pid = self._project_id()
        legacy_root = home / ".claude" / "plugins" / "data" / "xp-agents-xp-agents"
        smm = legacy_root / pid / "smm"
        (smm / "retrospectives").mkdir(parents=True)
        (smm / "events.jsonl").write_text(events)
        (smm / "sprint.json").write_text('{"sprint_id":"s1"}')
        (smm / "shared_mental_model.json").write_text("{}")
        (smm / "retrospectives" / "r1.json").write_text('{"keep":[]}')
        return smm

    def _migrate(self, home: Path) -> subprocess.CompletedProcess:
        """Run init.sh on the discovery path — XP_AGENTS_DATA unset."""
        return self._run_init(
            extra_env={"HOME": str(home)},
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )

    def _new_smm(self, home: Path) -> Path:
        return home / ".xp-agents" / "data" / self._project_id() / "smm"


class TestAutoMigration(_MigrationCase):
    def test_copies_legacy_to_new_root_and_returns_it(self):
        home = self._home("copy")
        legacy = self._seed_legacy(home)
        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(self._new_smm(home)))
        new = self._new_smm(home)
        self.assertEqual((new / "events.jsonl").read_text(), '{"e":1}\n')
        self.assertTrue((new / "retrospectives" / "r1.json").exists())
        self.assertEqual((new / "sprint.json").read_text(), '{"sprint_id":"s1"}')
        # Source survives — the whole safety story rests on this.
        self.assertTrue(legacy.exists())
        self.assertEqual((legacy / "events.jsonl").read_text(), '{"e":1}\n')

    def test_created_data_root_is_not_world_readable(self):
        """Same rule as a fresh SMM: narrow every dir WE create.

        Migration creates the data root itself, before the chmod at the end of
        init.sh — which then sees a root that already exists and leaves it
        alone. Without a narrow umask the whole temp copy of the SMM would sit
        in a world-readable dir while it is being written.
        """
        home = self._home("modes")
        self._seed_legacy(home)
        self.assertEqual(self._migrate(home).returncode, 0)
        for created in (
            home / ".xp-agents",
            home / ".xp-agents" / "data",
            self._new_smm(home).parent,
        ):
            self.assertEqual(
                created.stat().st_mode & 0o777, 0o700, f"{created} is too open"
            )

    def test_is_idempotent(self):
        home = self._home("idem")
        legacy = self._seed_legacy(home)
        first = self._migrate(home)
        self.assertEqual(first.returncode, 0, f"init.sh failed: {first.stderr}")

        # Diverge the two copies, then re-run: a second migration would clobber
        # the new tree with the legacy contents.
        (self._new_smm(home) / "events.jsonl").write_text('{"e":1}\n{"e":2}\n')
        second = self._migrate(home)
        self.assertEqual(second.returncode, 0, f"init.sh failed: {second.stderr}")
        self.assertEqual(second.stdout.strip(), first.stdout.strip())
        self.assertEqual(
            (self._new_smm(home) / "events.jsonl").read_text(), '{"e":1}\n{"e":2}\n'
        )
        self.assertEqual((legacy / "events.jsonl").read_text(), '{"e":1}\n')

    def test_leaves_a_forward_pointer_at_the_legacy_location(self):
        """A straggler pinned to the legacy path gets redirected.

        spawn_teammate exports SMM_DIR as an absolute path, so a process
        spawned just before migration keeps resolving the old tree. The pointer
        is what stops its appends landing somewhere nothing reads again.
        """
        home = self._home("pointer")
        legacy = self._seed_legacy(home)
        self._migrate(home)
        pointer = legacy / ".migrated-to"
        self.assertTrue(pointer.exists(), "expected a .migrated-to pointer")
        self.assertEqual(pointer.read_text().strip(), str(self._new_smm(home)))

    def test_pinned_smm_dir_follows_the_pointer(self):
        home = self._home("follow")
        legacy = self._seed_legacy(home)
        self._migrate(home)
        # Exactly what a pre-migration teammate inherits.
        result = self._run_init(extra_env={"SMM_DIR": str(legacy)})
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(self._new_smm(home)))

    def test_no_pointer_means_pinned_smm_dir_is_used_verbatim(self):
        """The pointer must not change SMM_DIR's meaning when absent — that is
        how every teammate spawn works."""
        target = self.tmpdir / "verbatim-smm"
        result = self._run_init(extra_env={"SMM_DIR": str(target)})
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(target))


class TestMigrationDeclines(_MigrationCase):
    """Cases where migrating would be unsafe, so it must not happen."""

    def test_declines_while_a_worktree_exists(self):
        home = self._home("worktree")
        legacy = self._seed_legacy(home)
        (legacy.parent / "worktrees" / "worktree-story-001").mkdir(parents=True)

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(
            result.stdout.strip(),
            str(legacy),
            "must keep using the legacy SMM while a teammate worktree is live",
        )
        self.assertFalse((home / ".xp-agents").exists())
        self.assertFalse(
            (legacy / ".migrated-to").exists(),
            "a pointer would redirect the live teammate at its next resolution",
        )

    def test_declines_while_an_in_place_teammate_marker_exists(self):
        """In-place teammates run in the MAIN checkout with no worktree dir at
        all — a worktree-only check misses them entirely."""
        home = self._home("inplace")
        legacy = self._seed_legacy(home)
        (legacy / ".in-place-active-worktree-story-002").write_text("live")

        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(legacy))
        self.assertFalse((home / ".xp-agents").exists())
        self.assertFalse((legacy / ".migrated-to").exists())

    def test_declining_is_not_sticky(self):
        """Declining records nothing, so the session after the teammate exits
        migrates normally. A sticky decline would strand the SMM in the
        uninstall-deleted directory for the life of the project."""
        home = self._home("unsticky")
        legacy = self._seed_legacy(home)
        worktree = legacy.parent / "worktrees" / "worktree-story-001"
        worktree.mkdir(parents=True)
        self.assertEqual(self._migrate(home).stdout.strip(), str(legacy))

        worktree.rmdir()
        result = self._migrate(home)
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(self._new_smm(home)))
        self.assertEqual(
            (self._new_smm(home) / "events.jsonl").read_text(), '{"e":1}\n'
        )

    def test_declines_when_explicit_root_is_named(self):
        """Same rule as discovery: legacy roots are consulted only when
        XP_AGENTS_DATA is unset. Otherwise auto-migration would COPY a live SMM
        into whatever root a sandboxed caller redirected to."""
        home = self._home("explicit")
        legacy = self._seed_legacy(home)
        explicit = self.tmpdir / "explicit-root"
        result = self._run_init(
            extra_env={"HOME": str(home), "XP_AGENTS_DATA": str(explicit)}
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertTrue(Path(result.stdout.strip()).is_relative_to(explicit))
        self.assertFalse(
            (legacy / ".migrated-to").exists(),
            "declining must not leave a pointer",
        )

    def test_unwritable_new_root_falls_back_to_legacy_and_exits_zero(self):
        """`set -e` must not turn a failed migration into a dead session.

        A non-zero mkdir/cp/mv would abort init.sh, _derive_smm_dir would get
        empty stdout, resolve_smm_dir would return None, and every hook in the
        session would degrade to no-SMM.

        The clean-stderr assertion is not cosmetic: bash 3.2 (macOS) does NOT
        inherit `set -e` into a command substitution, so on that shell an
        unguarded failure keeps going and can still print the right path. Exit
        code alone therefore proves nothing here, while the guard's `2>/dev/null`
        is observable on every shell.
        """
        home = self._home("unwritable")
        legacy = self._seed_legacy(home)
        blocked = home / ".xp-agents"
        blocked.mkdir()
        blocked.chmod(0o500)
        self.addCleanup(blocked.chmod, 0o700)

        result = self._migrate(home)
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh must not abort when migration fails: {result.stderr}",
        )
        self.assertEqual(result.stderr, "", "a guarded failure must stay quiet")
        self.assertEqual(result.stdout.strip(), str(legacy))
        self.assertEqual((legacy / "events.jsonl").read_text(), '{"e":1}\n')


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
        """A lock whose holder is gone must not deadlock the plugin forever."""
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
