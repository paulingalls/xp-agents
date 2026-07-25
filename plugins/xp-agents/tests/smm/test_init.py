#!/usr/bin/env python3
"""Tests for SMM initialization.

Covers TestInit, TestInitHonorsSmmDirEnv, TestSeedSMM.
Event validation tests live in test_event_validation.py.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Path setup -- allow importing production modules and conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from conftest import _PLUGIN_ROOT, _TempRepoTestCase

_REAL_PLUGIN_DATA_ROOT = (
    Path.home() / ".claude" / "plugins" / "data" / "xp-agents-xp-agents"
)


def _is_real_root(path: str | Path | None) -> bool:
    """True if path is the real plugin-data root or lives under it."""
    if not path:
        return False
    p = Path(path)
    return p == _REAL_PLUGIN_DATA_ROOT or _REAL_PLUGIN_DATA_ROOT in p.parents


class TestInit(_TempRepoTestCase):
    """Tests for smm/init.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def setUp(self) -> None:
        # Reset events.jsonl before each test
        (self.smm_dir / "events.jsonl").write_text("")

    def test_init_succeeds(self):
        result = self._run_init(extra_env={"SMM_DIR": ""})
        self.assertEqual(result.returncode, 0)
        smm_dir = result.stdout.strip()
        self.assertTrue(Path(smm_dir).is_dir())

    def test_init_idempotent(self):
        r1 = self._run_init(extra_env={"SMM_DIR": ""})
        r2 = self._run_init(extra_env={"SMM_DIR": ""})
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r1.stdout.strip(), r2.stdout.strip())

    def test_init_creates_structure(self):
        smm_dir = self._get_smm_dir()
        self.assertTrue((smm_dir / "events.jsonl").exists())
        self.assertTrue((smm_dir / "events.lock").exists())
        self.assertTrue((smm_dir / "retrospectives").is_dir())

    def test_init_events_file_permissions(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        mode = events_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.jsonl mode is {oct(mode)}")

    def test_init_lock_file_permissions(self):
        smm_dir = self._get_smm_dir()
        lock_file = smm_dir / "events.lock"
        mode = lock_file.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"events.lock mode is {oct(mode)}")

    def test_init_smm_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        mode = smm_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700, f"SMM dir mode is {oct(mode)}")

    def test_init_retrospectives_dir_permissions(self):
        smm_dir = self._get_smm_dir()
        retro_dir = smm_dir / "retrospectives"
        mode = retro_dir.stat().st_mode & 0o777
        self.assertEqual(
            mode,
            0o700,
            f"retrospectives dir mode is {oct(mode)}",
        )

    def test_init_does_not_truncate_existing(self):
        smm_dir = self._get_smm_dir()
        events_file = smm_dir / "events.jsonl"
        events_file.write_text("existing content\n")

        self._run_init()

        self.assertEqual(events_file.read_text(), "existing content\n")


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
    class pins only the precedence — the default root and legacy discovery land
    in later commits, so nothing resolved by an existing project changes yet.
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

    def test_unset_leaves_existing_behavior_unchanged(self):
        """Commit-1 safety property: with XP_AGENTS_DATA absent, every project
        resolves exactly where it did before.

        Must genuinely UNSET it — setUpClass pins XP_AGENTS_DATA as the suite's
        containment root, so `_run_init()` alone leaves it set and this would
        restate `test_xp_agents_data_is_used_when_set`.
        """
        legacy = self.tmpdir / "legacy-unset"
        result = self._run_init(
            extra_env=self._legacy_only_env(legacy), unset=("XP_AGENTS_DATA",)
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        self.assertTrue(
            derived.is_relative_to(legacy),
            f"expected {legacy}, got {derived}",
        )

    def test_empty_xp_agents_data_falls_through(self):
        """`:-` (not `-`) so an empty value falls through, same as unset.

        Supplies its OWN CLAUDE_PLUGIN_DATA: with the session pin now on
        XP_AGENTS_DATA, emptying it and relying on the ambient env would fall
        through to a REAL root and litter it.
        """
        legacy = self.tmpdir / "legacy-fallthrough"
        result = self._run_init(
            extra_env={"XP_AGENTS_DATA": "", **self._legacy_only_env(legacy)}
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        self.assertTrue(
            derived.is_relative_to(legacy),
            f"expected fallthrough to {legacy}, got {derived}",
        )

    def test_only_the_root_changes_not_the_project_id(self):
        """`{project-id}/smm` must be identical under either root.

        The later migration commits copy `<old-root>/<pid>/smm` to
        `<new-root>/<pid>/smm`; that is only sound while the root is the
        one and only thing XP_AGENTS_DATA changes. So the two arms must
        resolve via the two DIFFERENT vars, not two values of the same one.
        """
        root = self.tmpdir / "xp-data-suffix"
        legacy = self.tmpdir / "legacy-suffix"
        with_xp = self._run_init(extra_env={"XP_AGENTS_DATA": str(root)})
        without = self._run_init(
            extra_env=self._legacy_only_env(legacy), unset=("XP_AGENTS_DATA",)
        )
        self.assertEqual(with_xp.returncode, 0, f"init.sh failed: {with_xp.stderr}")
        self.assertEqual(without.returncode, 0, f"init.sh failed: {without.stderr}")
        self.assertEqual(
            Path(with_xp.stdout.strip()).relative_to(root),
            Path(without.stdout.strip()).relative_to(legacy),
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


class TestSeedSMM(_TempRepoTestCase):
    """Tests for seed_smm.py -- default SMM created by init.sh."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.smm_dir = cls._get_smm_dir()

    def _load_smm(self) -> dict:
        import json

        path = self.smm_dir / "shared_mental_model.json"
        return json.loads(path.read_text())

    def test_seed_creates_smm_file(self):
        smm_file = self.smm_dir / "shared_mental_model.json"
        self.assertTrue(
            smm_file.exists(),
            "init.sh should seed shared_mental_model.json",
        )

    def test_seed_has_four_pillars(self):
        smm = self._load_smm()
        for pillar in ("intent", "constraints", "risks", "wisdom"):
            self.assertIn(pillar, smm)
            self.assertIsInstance(smm[pillar], list)

    def test_seed_has_xp_constraints(self):
        smm = self._load_smm()
        contents = [e["content"] for e in smm["constraints"]]
        joined = " ".join(contents)
        self.assertIn("TDD", joined)
        self.assertIn("Small commits", joined)

    def test_seed_detects_missing_linter(self):
        """Fresh git repo has no linter -- should be flagged."""
        smm = self._load_smm()
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No linter configured", joined)

    def test_seed_detects_missing_hooks(self):
        """Fresh git repo has no hooks -- should be flagged."""
        smm = self._load_smm()
        contents = [e["content"] for e in smm["risks"]]
        joined = " ".join(contents)
        self.assertIn("No git commit hooks", joined)

    def test_seed_idempotent(self):
        """Running init.sh again does not overwrite existing SMM."""
        smm_file = self.smm_dir / "shared_mental_model.json"
        smm_file.write_text('{"custom": true}')
        self._run_init()
        self.assertEqual(smm_file.read_text(), '{"custom": true}')

    def test_seed_fires_when_only_old_md_exists(self):
        """Old .md present but no JSON -> seed fires."""
        json_file = self.smm_dir / "shared_mental_model.json"
        md_file = self.smm_dir / "SHARED_MENTAL_MODEL.md"
        json_file.unlink(missing_ok=True)
        md_file.write_text("# Old markdown SMM\n")
        self._run_init()
        self.assertTrue(json_file.exists())
        self.assertTrue(md_file.exists())
        self.assertEqual(md_file.read_text(), "# Old markdown SMM\n")


class TestPluginDataIsolation(unittest.TestCase):
    """conftest must pin XP_AGENTS_DATA to a throwaway dir for the whole
    test session.

    Regression for SMM dirs littering the real
    ~/.claude/plugins/data/xp-agents-xp-agents root: with SMM_DIR stripped by
    conftest, production code that derives its SMM in-process
    (resolve_smm_dir -> _derive_smm_dir -> init.sh, inheriting os.environ)
    would otherwise fall back to that real root, creating one project-id dir
    per ephemeral test git repo and leaving it behind.
    """

    def test_leaked_xp_agents_data_cannot_outrank_the_pin(self):
        """A dev exporting XP_AGENTS_DATA — the var's whole purpose — must not
        redirect the suite at their real SMM. conftest strips it and then pins
        its own value, so what survives is always the throwaway dir."""
        pd = os.environ.get("XP_AGENTS_DATA")
        self.assertTrue(pd, "conftest must pin XP_AGENTS_DATA")
        assert pd is not None
        self.assertTrue(
            Path(pd).name.startswith("xp-agents-test-plugin-data-"),
            f"XP_AGENTS_DATA must be conftest's own throwaway dir, got {pd!r}",
        )

    def test_plugin_data_env_is_isolated_tempdir(self):
        pd = os.environ.get("XP_AGENTS_DATA")
        self.assertTrue(pd, "conftest must set XP_AGENTS_DATA for test isolation")
        self.assertFalse(
            _is_real_root(pd),
            f"XP_AGENTS_DATA must be a throwaway dir, not the real "
            f"plugin-data root, got {pd!r}",
        )

    def test_ambient_init_resolves_under_isolated_root(self):
        # Assert the pin BEFORE invoking init.sh — when red (env not pinned)
        # this fails here, so the test never itself derives under the real
        # root and leaks a dir.
        pd = os.environ.get("XP_AGENTS_DATA")
        self.assertTrue(pd and not _is_real_root(pd), "env not isolated")
        assert pd is not None  # narrowed by the assertTrue above (for Pyright)

        # init.sh, run in a fresh temp git repo with the AMBIENT process env
        # (what production subprocess calls inherit) and SMM_DIR stripped,
        # must resolve under the pinned root.
        with tempfile.TemporaryDirectory() as repo:
            git_env = {
                **os.environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            }
            subprocess.run(
                ["git", "init", "-q", "."],
                cwd=repo,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "init"],
                cwd=repo,
                check=True,
                capture_output=True,
                env=git_env,
            )
            env = os.environ.copy()
            env.pop("SMM_DIR", None)
            result = subprocess.run(
                ["bash", str(_PLUGIN_ROOT / "smm" / "init.sh")],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            derived = Path(result.stdout.strip())
            self.assertTrue(
                derived.is_relative_to(pd),
                f"init.sh derived {derived}, expected under pinned {pd}",
            )
            self.assertFalse(
                _is_real_root(derived),
                f"init.sh leaked under the real plugin-data root: {derived}",
            )


if __name__ == "__main__":
    unittest.main()
