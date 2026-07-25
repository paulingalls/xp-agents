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

    def test_missing_home_does_not_raise(self):
        """HOME is unset in some hook processes; the advisory is not worth an
        exception on the SessionStart path."""
        os.environ.pop("HOME", None)
        target = self.tmp / "no-home" / "smm"
        target.mkdir(parents=True)
        self.assertFalse(self.mod.is_under_plugin_managed_root(target))


class TestSessionStartAdvisory(_AdvisoryCase):
    """The advisory rides the systemMessage, not additionalContext: the USER is
    the one who must act (close or remove the stale worktree), and a line in a
    10KB context blob is the silent-enforcement pattern this release exists to
    end."""

    def _legacy_smm(self, install_dir_name: str) -> Path:
        legacy = self.plugin_data / install_dir_name / "abc123" / "smm"
        legacy.mkdir(parents=True)
        return legacy

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


if __name__ == "__main__":
    unittest.main()
