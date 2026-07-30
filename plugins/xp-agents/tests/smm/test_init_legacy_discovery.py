#!/usr/bin/env python3
"""The DEFAULT root, discovery of an SMM under a legacy one, and the suite's own
isolation from the user's real SMM.

Split from `test_init.py` (724 lines). Grouped by the failure they guard rather
than by the code they call: all three are about an SMM landing somewhere it
should not — abandoned under an old root, or littered into the developer's live
one. The precedence rules are in `test_init_env_roots.py`.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Path setup -- allow importing production modules and conftest
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))
from _real_root_guard import _is_real_root
from conftest import _PLUGIN_ROOT, _TempRepoTestCase


class TestDefaultRootAndLegacyDiscovery(_TempRepoTestCase):
    """The default root is `~/.xp-agents/data`, and an SMM already living under
    a plugin-managed root is DISCOVERED there rather than abandoned.

    Without discovery, upgrading points every existing project at an empty new
    root — which presents as a brand-new project with no history, the exact
    silent loss this whole change exists to prevent.
    """

    def _fake_home(self, name: str) -> Path:
        home = self.tmpdir / f"home-{name}"
        home.mkdir(parents=True, exist_ok=True)
        return home

    def _project_id(self) -> str:
        """The project-id init.sh derives for this repo.

        Learned from a real derivation rather than re-deriving the hash here —
        duplicating production's hashing in a test is how the two drift.
        """
        probe = self.tmpdir / "probe-root"
        r = self._run_init(extra_env={"XP_AGENTS_DATA": str(probe)})
        self.assertEqual(r.returncode, 0, f"probe failed: {r.stderr}")
        return Path(r.stdout.strip()).parent.name

    def _seed_legacy(self, root: Path, marker: str = "seeded") -> Path:
        """Create a legacy SMM for this repo under `root`, return its path.

        Built directly rather than via init.sh: legacy roots are DISCOVERY-only,
        so pointing init.sh at one never writes there — which is the behavior
        these tests exist to pin.

        `marker` goes into events.jsonl so a test can prove WHICH candidate was
        picked up. Once migration relocates the tree, path equality no longer
        shows that, and a candidate-list test that cannot tell the candidates
        apart is not testing the list.
        """
        seeded = root / self._project_id() / "smm"
        (seeded / "retrospectives").mkdir(parents=True)
        (seeded / "events.jsonl").write_text(f'{{"from":"{marker}"}}\n')
        return seeded

    def test_default_root_is_xp_agents_data_under_home(self):
        home = self._fake_home("default")
        result = self._run_init(
            extra_env={"HOME": str(home)},
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        self.assertTrue(
            derived.is_relative_to(home / ".xp-agents" / "data"),
            f"expected default under {home}/.xp-agents/data, got {derived}",
        )

    def test_legacy_claude_plugin_data_is_discovered(self):
        legacy_root = self.tmpdir / "legacy-env-root"
        seeded = self._seed_legacy(legacy_root, "env-candidate")
        home = self._fake_home("discover-env")
        result = self._run_init(
            extra_env={"CLAUDE_PLUGIN_DATA": str(legacy_root), "HOME": str(home)},
            unset=("XP_AGENTS_DATA",),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        resolved = Path(result.stdout.strip())
        self.assertEqual(
            (resolved / "events.jsonl").read_text(), '{"from":"env-candidate"}\n'
        )
        self.assertTrue(seeded.exists(), "the source must survive")

    def test_legacy_marketplace_default_is_discovered(self):
        """CLAUDE_PLUGIN_DATA is absent in some hook processes, so the
        marketplace default must be its own candidate."""
        home = self._fake_home("marketplace")
        legacy_root = home / ".claude" / "plugins" / "data" / "xp-agents-xp-agents"
        seeded = self._seed_legacy(legacy_root, "marketplace")
        result = self._run_init(
            extra_env={"HOME": str(home)},
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        resolved = Path(result.stdout.strip())
        self.assertEqual(
            (resolved / "events.jsonl").read_text(), '{"from":"marketplace"}\n'
        )
        self.assertTrue(seeded.exists(), "the source must survive")

    def test_legacy_inline_dev_default_is_discovered(self):
        """Dev-mode installs resolve the plugin id to `xp-agents-inline`, so a
        plugin developer's own SMM lives under a different root than a
        marketplace user's."""
        home = self._fake_home("inline")
        legacy_root = home / ".claude" / "plugins" / "data" / "xp-agents-inline"
        seeded = self._seed_legacy(legacy_root, "inline-dev")
        result = self._run_init(
            extra_env={"HOME": str(home)},
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        resolved = Path(result.stdout.strip())
        self.assertEqual(
            (resolved / "events.jsonl").read_text(), '{"from":"inline-dev"}\n'
        )
        self.assertTrue(seeded.exists(), "the source must survive")

    def test_legacy_source_survives_relocation(self):
        """Replaces commit 3's `test_legacy_is_used_in_place_not_copied`.

        That test pinned "discovered, never copied", which was accurate while
        migration did not exist. Migration COPIES — and the property that
        actually matters is unchanged and now load-bearing: the source is never
        deleted, so an interrupted or wrong relocation loses nothing.
        """
        home = self._fake_home("survives")
        legacy_root = home / ".claude" / "plugins" / "data" / "xp-agents-xp-agents"
        seeded = self._seed_legacy(legacy_root, "original")

        result = self._run_init(
            extra_env={"HOME": str(home)},
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        resolved = Path(result.stdout.strip())
        self.assertTrue(resolved.is_relative_to(home / ".xp-agents" / "data"))
        self.assertTrue(seeded.exists())
        self.assertEqual((seeded / "events.jsonl").read_text(), '{"from":"original"}\n')

    def test_explicit_xp_agents_data_skips_legacy_discovery(self):
        """An explicitly named root is AUTHORITATIVE — no hunting elsewhere.

        Discovery exists for the upgrade path, where XP_AGENTS_DATA is unset and
        we must find an SMM the previous version left under a plugin-data root.
        When a caller names a root, going looking anyway is both wrong (they
        said where) and unsafe: the whole test suite pins this var, so
        discovery would resolve the REAL repo's SMM under the developer's real
        HOME for any test whose cwd is this repo. That happened — 19 tests
        resolved a live SMM.
        """
        home = self._fake_home("explicit")
        legacy_root = home / ".claude" / "plugins" / "data" / "xp-agents-xp-agents"
        seeded = self._seed_legacy(legacy_root)
        (seeded / "events.jsonl").write_text('{"marker":"legacy"}\n')
        explicit = self.tmpdir / "explicit-root"

        result = self._run_init(
            extra_env={"XP_AGENTS_DATA": str(explicit), "HOME": str(home)}
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        derived = Path(result.stdout.strip())
        self.assertTrue(
            derived.is_relative_to(explicit),
            f"explicit root must win, got {derived}",
        )
        # And the legacy SMM is left completely alone.
        self.assertEqual((seeded / "events.jsonl").read_text(), '{"marker":"legacy"}\n')

    def test_new_root_wins_when_both_exist(self):
        """An SMM at the DEFAULT root stops legacy discovery.

        Exercised with XP_AGENTS_DATA unset, because that is the only path where
        "both exist" is a real contest: an explicitly named root skips discovery
        outright, so pinning it there would restate
        `test_explicit_xp_agents_data_skips_legacy_discovery` and leave the
        new-root-exists check itself untested. Verified by mutation — deleting
        that check from init.sh left the whole file green before this test.

        It is load-bearing for the migration commit: once a copy lands at the new
        root, this is what stops every later process re-resolving the stale
        legacy tree.
        """
        home = self._fake_home("both")
        legacy_root = home / ".claude" / "plugins" / "data" / "xp-agents-xp-agents"
        legacy = self._seed_legacy(legacy_root)
        (legacy / "events.jsonl").write_text('{"marker":"legacy"}\n')
        new_smm = home / ".xp-agents" / "data" / self._project_id() / "smm"
        new_smm.mkdir(parents=True)

        result = self._run_init(
            extra_env={"HOME": str(home)},
            unset=("XP_AGENTS_DATA", "CLAUDE_PLUGIN_DATA"),
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(result.stdout.strip(), str(new_smm))
        self.assertEqual((legacy / "events.jsonl").read_text(), '{"marker":"legacy"}\n')

    def test_explicit_root_does_not_require_home(self):
        """`nounset` + an unset $HOME must not break the explicit-root path.

        The legacy candidate list interpolates $HOME, so building it before the
        branch that reads it made `XP_AGENTS_DATA=<path>` with $HOME absent exit 1
        on a list that path never consults — init.sh is the single resolver for
        every script and hook, so that is total failure, not degradation. It
        worked before the discovery change; bash short-circuits nested `:-`
        defaults, so `${HOME}` was never expanded when the outer var was set.
        """
        root = self.tmpdir / "no-home-root"
        result = self._run_init(
            extra_env={"XP_AGENTS_DATA": str(root)}, unset=("HOME",)
        )
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertTrue(Path(result.stdout.strip()).is_relative_to(root))

    def test_preexisting_base_dir_is_not_chmodded(self):
        """`XP_AGENTS_DATA=$HOME` must not chmod 700 the user's home.

        BASE_DIR used to always be the plugin-owned data dir; it is now any
        path the user names, and the whole point of the var is that they name
        one. Only dirs init.sh CREATED may have their mode narrowed.
        """
        preexisting = self.tmpdir / "user-owned-root"
        preexisting.mkdir(mode=0o755)
        self.assertEqual(preexisting.stat().st_mode & 0o777, 0o755)

        result = self._run_init(extra_env={"XP_AGENTS_DATA": str(preexisting)})
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(
            preexisting.stat().st_mode & 0o777,
            0o755,
            "init.sh chmodded a data root it did not create",
        )

    def test_created_base_dir_is_chmodded_700(self):
        """The narrowing still happens for roots we do create — dropping it
        would leave a fresh SMM tree world-readable."""
        fresh = self.tmpdir / "fresh-root" / "nested"
        result = self._run_init(extra_env={"XP_AGENTS_DATA": str(fresh)})
        self.assertEqual(result.returncode, 0, f"init.sh failed: {result.stderr}")
        self.assertEqual(fresh.stat().st_mode & 0o777, 0o700)


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


if __name__ == "__main__":
    unittest.main()
