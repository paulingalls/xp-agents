#!/usr/bin/env python3
"""Tests for the plugin-managed-root advisory.

An SMM under a plugin-managed data root is one `claude plugin uninstall`
away from gone (the CLI deletes that directory by default). v5.0.0 relocates
it automatically — but relocation DECLINES while any teammate worktree or
in-place marker is present, and nothing removes a worktree directory whose
branch never merged. So the declined state can persist indefinitely, with no
in-product signal that the project's memory is still sitting in the deletable
directory. This advisory is that signal.

Covers both halves: the `is_under_plugin_managed_root` predicate (which roots
count, and which explicitly do NOT) and the SessionStart systemMessage that
carries it to the user.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))


class _AdvisoryCase(unittest.TestCase):
    """Per-test HOME and data root, so nothing here can read the developer's
    real SMM or leave a directory behind in a shared temp root."""

    def setUp(self):
        import smm_dir_resolve

        self.mod = smm_dir_resolve
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = self.tmp / "home"
        self.plugin_data = self.home / ".claude" / "plugins" / "data"
        self.plugin_data.mkdir(parents=True)
        self._set_env("HOME", str(self.home))
        # Point the host variable somewhere real but empty by default; tests
        # that care override it. Leaving it inherited would let the developer's
        # own root decide the outcome.
        self._set_env("CLAUDE_PLUGIN_DATA", str(self.tmp / "unset-host-root"))
        # conftest's `_env_hygiene` pins XP_AGENTS_DATA to a throwaway dir for
        # the whole pytest session (belt-and-braces against other suites
        # littering a real root). That pin outranks HOME in destination_for,
        # so without unsetting it here, migration_lock.lock_state resolves
        # the lock under the SESSION-wide throwaway dir instead of self.home,
        # and every lock this file creates under self.home goes unseen.
        self._set_env("XP_AGENTS_DATA", None)

    def _set_env(self, name: str, value: str | None):
        prior = os.environ.get(name)

        def restore():
            if prior is not None:
                os.environ[name] = prior
            else:
                os.environ.pop(name, None)

        self.addCleanup(restore)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def _legacy_smm(self, install_dir_name: str) -> Path:
        legacy = self.plugin_data / install_dir_name / "abc123" / "smm"
        legacy.mkdir(parents=True)
        return legacy

    def _lock(self) -> Path:
        """The lock beside the DESTINATION project dir, not beside the SMM
        (init.sh: `project_dir="$(dirname "${new}")"` where `new` is the
        destination). `XP_AGENTS_DATA` is unset in setUp, so `destination_for`
        resolves under `Path.home()`, and the project id matches
        `_legacy_smm`'s hardcoded "abc123"."""
        lock = self.home / ".xp-agents" / "data" / "abc123" / ".migrate.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        return lock


class TestIsUnderPluginManagedRoot(_AdvisoryCase):
    """The predicate is a POSITIVE test against the roots that carry the
    uninstall risk, never a negative test against the preferred root — a user
    who deliberately points the data-root override or the SMM handle elsewhere
    is not at risk and must not be nagged every session."""

    def _under(self, path: Path) -> bool:
        path.mkdir(parents=True, exist_ok=True)
        return self.mod.is_under_plugin_managed_root(path)

    def test_marketplace_install_root_is_flagged(self):
        self.assertTrue(
            self._under(self.plugin_data / "xp-agents-xp-agents" / "abc123" / "smm")
        )

    def test_dev_mode_install_root_is_flagged(self):
        """A dev-mode install resolves the plugin id differently, and its data
        root is deleted by the same uninstall."""
        self.assertTrue(
            self._under(self.plugin_data / "xp-agents-inline" / "abc123" / "smm")
        )

    def test_claude_plugin_data_env_root_is_flagged(self):
        """The host names the root explicitly; honor it over the guesses so a
        non-default plugin-data location is still recognized as at-risk."""
        env_root = self.tmp / "harness-data"
        self._set_env("CLAUDE_PLUGIN_DATA", str(env_root))
        self.assertTrue(self._under(env_root / "abc123" / "smm"))

    def test_new_default_root_is_not_flagged(self):
        self.assertFalse(
            self._under(self.home / ".xp-agents" / "data" / "abc123" / "smm")
        )

    def test_unrelated_path_is_not_flagged(self):
        self.assertFalse(self._under(self.tmp / "somewhere" / "else" / "smm"))

    def test_sibling_directory_is_not_flagged(self):
        """`.../data/xp-agents-xp-agents-backup` shares a prefix but is not
        under the root — a string `startswith` would wrongly flag it."""
        self.assertFalse(
            self._under(self.plugin_data / "xp-agents-xp-agents-backup" / "smm")
        )

    def test_named_data_root_is_not_flagged_even_under_a_managed_root(self):
        """An explicitly-set XP_AGENTS_DATA is the user's own choice of root,
        and init.sh treats it as authoritative — it skips discovery AND
        relocation entirely. Warning here produces an advisory nothing can
        clear: the tool it names resolves to the same path and reports
        "relocation did not happen".
        """
        named = self.plugin_data / "xp-agents-xp-agents"
        self._set_env("XP_AGENTS_DATA", str(named))
        self.assertFalse(self._under(named / "abc123" / "smm"))

    def test_a_named_root_does_not_silence_a_different_managed_root(self):
        """Only the root they NAMED is exempt. A teammate whose SMM handle was
        pinned to a legacy tree is still at risk and must still be warned."""
        self._set_env("XP_AGENTS_DATA", str(self.tmp / "elsewhere"))
        self.assertTrue(
            self._under(self.plugin_data / "xp-agents-xp-agents" / "abc123" / "smm")
        )

    def test_missing_home_does_not_raise(self):
        """`Path.home()` can raise RuntimeError with no resolvable home; the
        advisory is not worth an exception on the SessionStart path.

        Popping HOME alone does not force this: `expanduser` falls back to
        the passwd database (`env -u HOME python3 -c "print(Path.home())"`
        still returns the real home), so a pop-only test passes whether or
        not anything here guards the exception. Patch `Path.home` in
        `smm_dir_resolve`'s own namespace instead, with HOME left set.
        """
        with mock.patch("smm_dir_resolve.Path.home", side_effect=RuntimeError):
            target = self.tmp / "no-home" / "smm"
            target.mkdir(parents=True)
            self.assertFalse(self.mod.is_under_plugin_managed_root(target))


class TestSessionStartAdvisory(_AdvisoryCase):
    """The advisory rides the systemMessage, not additionalContext: the USER is
    the one who must act (close or remove the stale worktree), and a line in a
    10KB context blob is the silent-enforcement pattern this release exists to
    end."""

    def test_advisory_present_when_smm_is_under_plugin_managed_root(self):
        import session_start

        msg = session_start._system_message(
            "startup", "9.9.9", self._legacy_smm("xp-agents-xp-agents")
        )
        self.assertIn("uninstall", msg)
        self.assertIn("teammate", msg)
        # Names the tool that answers "what is holding it", with a real path —
        # an advisory that states a problem and no next step is just noise.
        self.assertIn("migrate_smm_root.py", msg)
        self.assertNotIn("{tool}", msg)

    def test_advisory_names_the_tool_under_the_live_plugin_root(self):
        """Pins the whole path, not just the basename: the cache is versioned,
        so the advisory resolves the root at message time — a wrong subdirectory
        or a hardcoded path would still contain the basename and pass the
        assertion above."""
        import session_start

        root = self.tmp / "cache" / "xp-agents" / "9.9.9"
        self._set_env("CLAUDE_PLUGIN_ROOT", str(root))
        msg = session_start._system_message(
            "startup", "9.9.9", self._legacy_smm("xp-agents-xp-agents")
        )
        # Invoked via python3: the script ships mode 644 like every other CLI
        # here, so a bare path pasted at a shell would just say "permission
        # denied".
        self.assertIn(
            f"python3 {root / 'scripts' / 'migrate_smm_root.py'}",
            msg,
        )

    def test_no_advisory_for_safe_root(self):
        import session_start

        safe = self.home / ".xp-agents" / "data" / "abc123" / "smm"
        safe.mkdir(parents=True)
        msg = session_start._system_message("startup", "9.9.9", safe)
        self.assertNotIn("uninstall", msg)

    def test_no_advisory_when_dir_unknown(self):
        """Resolution failed; an advisory guessing at the path would be worse
        than silence."""
        import session_start

        msg = session_start._system_message("startup", "9.9.9", None)
        self.assertNotIn("uninstall", msg)

    def test_advisory_rides_alongside_the_kickoff_nudge(self):
        """Both matter on a fresh start; the advisory must not displace the
        nudge that drives every session."""
        import session_start

        msg = session_start._system_message(
            "startup", "9.9.9", self._legacy_smm("xp-agents-inline")
        )
        self.assertIn("xp-kickoff", msg)
        self.assertIn("uninstall", msg)
        self.assertIn("9.9.9", msg)


class TestSessionStartAdvisoryByLockState(_AdvisoryCase):
    """A crashed relocation's lock never self-releases on its own — see
    `plugins/xp-agents/smm/init.sh:138-151`. So the same at-risk-root advisory
    that fires today for "no lock yet" must differentiate by remedy once a
    lock exists, or a stalled/blocked user gets the same "it relocates itself
    automatically" wording forever with no escape hatch.
    """

    def test_dead_holder_says_stalled_and_names_confirm_directly(self):
        import session_start

        legacy = self._legacy_smm("xp-agents-xp-agents")
        self._lock().symlink_to("999999")
        msg = session_start._system_message("startup", "9.9.9", legacy)
        self.assertIn("stalled", msg)
        self.assertIn("--confirm", msg)

    def test_live_holder_says_in_progress_and_withholds_confirm(self):
        """The only state that must NOT suggest --confirm: guessing at a
        RUNNING holder is exactly the "restore the automatic breaker" mistake
        this story exists to avoid. This negative is the whole point — without
        it, one advisory string could satisfy both the live and dead cases."""
        import session_start

        legacy = self._legacy_smm("xp-agents-xp-agents")
        self._lock().symlink_to(str(os.getpid()))
        msg = session_start._system_message("startup", "9.9.9", legacy)
        self.assertIn("in progress", msg)
        self.assertIn("migrate_smm_root.py", msg)
        self.assertNotIn("--confirm", msg)

    def test_unverifiable_holder_says_blocked_and_points_to_the_report(self):
        """Never self-releases, so it must not be left a dead end — but
        --confirm must not be offered the same way the stalled case offers
        it (unqualified), since liveness here was never established."""
        import session_start

        legacy = self._legacy_smm("xp-agents-xp-agents")
        tool = (
            self.tmp
            / "cache"
            / "xp-agents"
            / "9.9.9"
            / "scripts"
            / "migrate_smm_root.py"
        )
        self._set_env("CLAUDE_PLUGIN_ROOT", str(tool.parent.parent))
        self._lock().symlink_to("not-a-pid")
        msg = session_start._system_message("startup", "9.9.9", legacy)
        self.assertIn("blocked", msg)
        self.assertIn(str(tool), msg)
        self.assertNotIn(f"{tool} --confirm", msg)

    def test_non_symlink_residue_says_blocked_and_points_to_the_report(self):
        """Same remedy, same message as the unverifiable-holder shape — both
        never self-release."""
        import session_start

        legacy = self._legacy_smm("xp-agents-xp-agents")
        self._lock().write_text("residue from an older init.sh")
        msg = session_start._system_message("startup", "9.9.9", legacy)
        self.assertIn("blocked", msg)
        self.assertIn("migrate_smm_root.py", msg)

    def test_no_lock_at_all_keeps_todays_wording(self):
        """Proves the new lock branches did not swallow the existing
        no-lock-yet path — `TestSessionStartAdvisory` exercises that wording
        too, but explicitly excluding "stalled"/"in progress"/"blocked" here
        pins that they are genuinely absent."""
        import session_start

        legacy = self._legacy_smm("xp-agents-xp-agents")
        msg = session_start._system_message("startup", "9.9.9", legacy)
        self.assertIn("uninstall", msg)
        self.assertNotIn("stalled", msg)
        self.assertNotIn("in progress", msg)
        self.assertNotIn("blocked", msg)

    def test_safe_root_stays_silent_even_with_a_lock_present(self):
        """A safe root's own lock (mid-relocation-out of some OTHER legacy
        tree, in principle) must not make an already-safe SMM start nagging —
        the predicate gates this branch exactly as it gates the no-lock one."""
        import session_start

        safe = self.home / ".xp-agents" / "data" / "abc123" / "smm"
        safe.mkdir(parents=True)
        self._lock().symlink_to("999999")
        msg = session_start._system_message("startup", "9.9.9", safe)
        self.assertNotIn("uninstall", msg)
        self.assertNotIn("stalled", msg)


class TestLockStateNeverRaises(_AdvisoryCase):
    """Total: `lock_state` must return a verdict instead of raising and
    taking out the whole SessionStart systemMessage. One leg per call that can
    raise — they are separate syscalls with separate failure modes, so no one
    of them covers another.

    A failed probe answers `unprobeable`, NOT `free`. `free` carries a claim
    ("it relocates itself automatically") that is false precisely when the
    probe failed: the commonest cause is a root-owned destination from one
    sudo'd run, which also blocks the relocation init.sh would otherwise do.
    Answering `free` printed a remedy that would fail for the same reason the
    probe did, and left the user never pointed at `--confirm`.
    """

    def test_a_vanished_lock_is_free(self):
        """The one probe failure that IS free: the lock was released between
        `is_symlink` and `readlink`, so ENOENT means gone, not unreadable."""
        import migration_lock

        legacy = self._legacy_smm("xp-agents-xp-agents")
        self._lock().symlink_to("999999")
        with mock.patch("os.readlink", side_effect=FileNotFoundError(2, "gone")):
            self.assertEqual(migration_lock.lock_state(legacy), "free")

    def test_an_unreadable_readlink_is_unprobeable(self):
        """Any OTHER readlink failure (EACCES, EIO) says nothing about whether
        a lock is there, so it must not be reported as absent."""
        import migration_lock

        legacy = self._legacy_smm("xp-agents-xp-agents")
        self._lock().symlink_to("999999")
        with mock.patch("os.readlink", side_effect=PermissionError(13, "denied")):
            self.assertEqual(migration_lock.lock_state(legacy), "unprobeable")

    def test_an_unresolvable_home_does_not_raise(self):
        """`lock_state` -> `lock_path_for` -> `destination_for` calls
        `Path.home()`, which raises RuntimeError on a hook process with no
        resolvable home. `destination_for` was written for a human-run CLI
        where that could not happen; it now runs in a hook on every session.
        """
        import migration_lock

        legacy = self._legacy_smm("xp-agents-xp-agents")
        with mock.patch("migration_lock.Path.home", side_effect=RuntimeError):
            self.assertEqual(migration_lock.lock_state(legacy), "unprobeable")

    def test_an_unsearchable_destination_dir_does_not_raise(self):
        """`Path.is_symlink()` PROPAGATES EACCES on every interpreter before
        3.14 — 3.11/3.12/3.13 go through `lstat()` + `_ignore_error`, whose
        ignore list is ENOENT/ENOTDIR/EBADF/ELOOP and does NOT include
        EACCES; only 3.14's rewrite onto `os.path.islink` swallows it. So a
        destination project dir this session cannot search (one sudo'd run
        leaving it root-owned is enough) tracebacks out of `_system_message`
        and costs the user the WHOLE SessionStart payload, not just the
        advisory.

        Patched rather than chmod-ed on purpose: a real chmod pins this only
        on the three interpreters that raise, and passes vacuously on the one
        a developer is most likely to be running.
        """
        import migration_lock

        legacy = self._legacy_smm("xp-agents-xp-agents")
        with mock.patch(
            "migration_lock.Path.is_symlink",
            side_effect=PermissionError(13, "Permission denied"),
        ):
            self.assertEqual(migration_lock.lock_state(legacy), "unprobeable")

    def test_an_unsearchable_dir_under_a_non_symlink_does_not_raise(self):
        """`Path.exists()` is a SECOND probe with the same pre-3.14 EACCES
        behaviour, reached only once `is_symlink()` has already answered
        False — so it needs its own leg, not coverage by the one above."""
        import migration_lock

        legacy = self._legacy_smm("xp-agents-xp-agents")
        with (
            mock.patch("migration_lock.Path.is_symlink", return_value=False),
            mock.patch(
                "migration_lock.Path.exists",
                side_effect=PermissionError(13, "Permission denied"),
            ),
        ):
            self.assertEqual(migration_lock.lock_state(legacy), "unprobeable")

    def test_an_unprobeable_lock_does_not_promise_automatic_relocation(self):
        """The consequence at the surface. init.sh never breaks a lock on its
        own, so telling a user whose destination is root-owned to wait for an
        automatic relocation is a false statement that leaves the SMM under the
        root `claude plugin uninstall` deletes."""
        import session_start

        legacy = self._legacy_smm("xp-agents-xp-agents")
        with mock.patch(
            "migration_lock.Path.is_symlink",
            side_effect=PermissionError(13, "Permission denied"),
        ):
            msg = session_start._system_message("startup", "9.9.9", legacy)
        self.assertIn("uninstall", msg)
        self.assertNotIn("relocates itself automatically", msg)
        self.assertIn("could not be determined", msg)
        self.assertIn("migrate_smm_root.py", msg)


if __name__ == "__main__":
    unittest.main()
