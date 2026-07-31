#!/usr/bin/env python3
"""init.sh's SMM-root PRECEDENCE: SMM_DIR, then XP_AGENTS_DATA.

Split from `test_init.py` (724 lines). These two classes answer one question —
which env var wins, and what an empty value falls through to — which is separate
from whether init.sh creates a correct tree (still in `test_init.py`) and from
where an SMM already on disk is found (`test_init_legacy_discovery.py`).
"""

import subprocess
import sys
import unittest
from pathlib import Path

# Path setup -- allow importing production modules and conftest
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from _real_root_guard import _is_real_root
from conftest import _TempRepoTestCase


class TestInitHonorsSmmDirEnv(_TempRepoTestCase):
    """When SMM_DIR env var is set, init.sh uses that path."""

    def _run_init_with_smm(self, smm_dir: str | Path) -> subprocess.CompletedProcess:
        return self._run_init(extra_env={"SMM_DIR": str(smm_dir)})

    def test_echoes_smm_dir_when_set(self):
        target = self.tmpdir / "custom-smm"
        result = self._run_init_with_smm(target)
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertEqual(result.stdout.strip(), str(target))

    def test_creates_structure_at_smm_dir(self):
        target = self.tmpdir / "custom-smm-structure"
        result = self._run_init_with_smm(target)
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertTrue(target.is_dir(), "target dir should exist")
        self.assertTrue((target / "events.jsonl").exists())
        self.assertTrue((target / "events.lock").exists())
        self.assertTrue((target / "retrospectives").is_dir())

    def test_creates_nested_nonexistent_path(self):
        target = self.tmpdir / "deep" / "nested" / "path" / "smm"
        result = self._run_init_with_smm(target)
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertTrue(target.is_dir())

    def test_idempotent_on_rerun(self):
        target = self.tmpdir / "idempotent-smm"
        r1 = self._run_init_with_smm(target)
        (target / "events.jsonl").write_text("existing\n")
        r2 = self._run_init_with_smm(target)
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())
        self.assertEqual((target / "events.jsonl").read_text(), "existing\n")

    def test_empty_smm_dir_falls_through_to_derivation(self):
        """Empty string should derive normally."""
        result = self._run_init_with_smm("")
        self.assertEqual(result.returncode, 0)
        derived = Path(result.stdout.strip())
        self.assertTrue(
            derived.is_relative_to(self._plugin_data_dir),
            f"expected derived path under {self._plugin_data_dir}, got {derived}",
        )

    def test_inherited_base_dir_is_not_chmodded(self):
        """When SMM_DIR is set, BASE_DIR must NOT be chmodded."""
        target = self.tmpdir / "custom-smm-no-basedir-leak"
        stray = self.tmpdir / "stray-base-dir"
        stray.mkdir(mode=0o755)
        original_mode = stray.stat().st_mode & 0o777
        self.assertEqual(original_mode, 0o755)

        result = self._run_init(
            extra_env={
                "SMM_DIR": str(target),
                "BASE_DIR": str(stray),
            }
        )
        self.assertEqual(
            result.returncode,
            0,
            f"init.sh failed: {result.stderr}",
        )
        self.assertEqual(
            stray.stat().st_mode & 0o777,
            0o755,
            "init.sh leaked chmod to an inherited BASE_DIR",
        )


class TestInitHonorsXpAgentsDataEnv(_TempRepoTestCase):
    """`XP_AGENTS_DATA` is the top-preference SMM data root.

    Step 1 of moving the SMM out of the plugin-managed data directory: that
    directory is DELETED by `claude plugin uninstall` (see CHANGELOG), so the
    root has to become something no plugin lifecycle operation touches. This
    class pins the precedence rules; TestDefaultRootAndLegacyDiscovery pins the
    default root and discovery of an SMM already living under a legacy root.
    """

    def _legacy_only_env(self, legacy_root: Path) -> dict:
        """Env whose ONLY reachable data root is `legacy_root`.

        HOME is redirected too. Without it, containment for the tests that
        disable XP_AGENTS_DATA rests entirely on init.sh keeping
        CLAUDE_PLUGIN_DATA in the chain — drop or reorder that leg (commit 3
        changes the default root) and derivation lands in the developer's real
        ~/.claude tree. Verified: with that leg removed these tests write a
        project-id dir into the real root.
        """
        return {
            "CLAUDE_PLUGIN_DATA": str(legacy_root),
            "HOME": str(self.tmpdir / "fake-home"),
        }

    def test_xp_agents_data_is_used_when_set(self):
        root = self.tmpdir / "xp-data-root"
        result = self._run_init(extra_env={"XP_AGENTS_DATA": str(root)})
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        self.assertTrue(
            derived.is_relative_to(root),
            f"expected derived path under {root}, got {derived}",
        )
        self.assertEqual(derived.name, "smm")

    def test_xp_agents_data_outranks_claude_plugin_data(self):
        """The whole point: the harness always sets CLAUDE_PLUGIN_DATA, so a
        chain that lets it win would be a no-op for every real user.

        Sets BOTH roots explicitly. `self._plugin_data_dir` is the value of
        XP_AGENTS_DATA now, not CLAUDE_PLUGIN_DATA, so asserting against it
        would prove nothing about precedence — deleting CLAUDE_PLUGIN_DATA
        from init.sh's chain entirely would leave that version green.
        """
        winner = self.tmpdir / "xp-data-wins"
        loser = self.tmpdir / "claude-data-loses"
        result = self._run_init(
            extra_env={
                "XP_AGENTS_DATA": str(winner),
                "CLAUDE_PLUGIN_DATA": str(loser),
            }
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        self.assertTrue(derived.is_relative_to(winner), f"got {derived}")
        self.assertFalse(
            derived.is_relative_to(loser),
            "CLAUDE_PLUGIN_DATA must not win over XP_AGENTS_DATA",
        )
        self.assertFalse(loser.exists(), "the losing root must not be created")

    def test_smm_dir_still_outranks_xp_agents_data(self):
        """SMM_DIR stays the single canonical handle — it is how a teammate
        spawner propagates the lead's SMM across a process boundary."""
        target = self.tmpdir / "explicit-smm"
        result = self._run_init(
            extra_env={
                "SMM_DIR": str(target),
                "XP_AGENTS_DATA": str(self.tmpdir / "ignored-root"),
            }
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(target))

    def test_unset_now_defaults_to_the_neutral_root(self):
        """With XP_AGENTS_DATA absent, a project with no existing SMM lands at
        the neutral default root.

        This DELIBERATELY replaces commit 1's no-op property ("resolves exactly
        where it did before"). Commit 1 scoped itself to precedence so it could
        not move data; changing the default is the point of this commit, and the
        contract change is visible here rather than hidden in a deletion.

        Must genuinely UNSET it — setUpClass pins XP_AGENTS_DATA as the suite's
        containment root, so `_run_init()` alone leaves it set and this would
        restate `test_xp_agents_data_is_used_when_set`.
        """
        legacy = self.tmpdir / "legacy-unset"
        env = self._legacy_only_env(legacy)
        result = self._run_init(extra_env=env, unset=("XP_AGENTS_DATA",))
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        # Nothing to discover under the legacy root, so the neutral default wins.
        self.assertTrue(
            derived.is_relative_to(Path(env["HOME"]) / ".xp-agents" / "data"),
            f"expected the neutral default root, got {derived}",
        )
        self.assertFalse(derived.is_relative_to(legacy))

    def test_empty_xp_agents_data_falls_through(self):
        """`:-` (not `-`) so an empty value behaves as unset — landing at the
        default root, since CLAUDE_PLUGIN_DATA is discovery-only."""
        home = self.tmpdir / "home-empty"
        home.mkdir(parents=True, exist_ok=True)
        result = self._run_init(
            extra_env={"XP_AGENTS_DATA": "", "HOME": str(home)},
            unset=("CLAUDE_PLUGIN_DATA",),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        self.assertTrue(
            derived.is_relative_to(home / ".xp-agents" / "data"),
            f"expected default root, got {derived}",
        )

    def test_only_the_root_changes_not_the_project_id(self):
        """`{project-id}/smm` must be identical under any root.

        The later migration copies `<old>/<pid>/smm` to `<new>/<pid>/smm`, so a
        root-dependent project-id would silently strand history. Two
        XP_AGENTS_DATA roots, because the legacy var is discovery-only and
        cannot be written to.
        """
        root_a = self.tmpdir / "root-a"
        root_b = self.tmpdir / "root-b"
        a = self._run_init(extra_env={"XP_AGENTS_DATA": str(root_a)})
        b = self._run_init(extra_env={"XP_AGENTS_DATA": str(root_b)})
        self.assertEqual(a.returncode, 0, f"init.sh failed: {a.stderr}")
        self.assertEqual(b.returncode, 0, f"init.sh failed: {b.stderr}")
        self.assertEqual(
            Path(a.stdout.strip()).relative_to(root_a),
            Path(b.stdout.strip()).relative_to(root_b),
        )

    def test_never_resolves_under_the_real_root(self):
        result = self._run_init(
            extra_env={"XP_AGENTS_DATA": str(self.tmpdir / "isolated")}
        )
        # Assert success first: a failed init.sh prints nothing, and
        # _is_real_root("") is False, so the real assertion would pass
        # vacuously on any breakage.
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = result.stdout.strip()
        self.assertTrue(derived, "init.sh must echo the resolved SMM dir")
        self.assertFalse(_is_real_root(derived))


if __name__ == "__main__":
    unittest.main()
