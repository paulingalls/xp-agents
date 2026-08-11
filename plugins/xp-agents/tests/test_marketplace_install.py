#!/usr/bin/env python3
"""The second harness really registers this repo and installs the plugin.

The sibling `test_marketplace_catalogs` pins the two catalogs' SHAPE by reading
JSON — hermetic, always runs. This file proves the shape is the one the harness
actually accepts, by shelling out to it. That split is why the two are separate
modules: everything here needs the CLI on PATH and skips without it, and every
row writes to a throwaway home.

Schema pins alone would not carry the claim. `marketplace add` was measured
returning zero against this repo while the catalog did not exist at all, so
registration proves nothing on its own — the load is asserted from the listing,
and the install from reading the plugin back out of the tree it produced.

The harness plumbing lives in `_codex_harness`, shared with the Milestone 8
capstone that installs from this same catalog and with `test_install_docs`, which
drives the documented sequence. Its docstrings carry the measured traps (the
`source.path`-compares-a-directory-with-itself one especially); a second copy here
would be a second thing to keep true.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _codex_harness import (
    _HARNESS,
    _PLUGIN_ID,
    _REPO_ROOT,
    _harness,
    _installed_entry,
    _installed_root,
    _isolated_home,
    assert_module_skips_without_harness,
)
from _paths import _PLUGIN_ROOT


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestRealRegistrationAndInstall(unittest.TestCase):
    """Register the repo as a marketplace, install from it, read the result."""

    def _registered_home(self) -> dict:
        """A fresh home with this repo registered, cleaned up with the test."""
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        added = _harness(env, "marketplace", "add", str(_REPO_ROOT))
        self.assertEqual(added.returncode, 0, added.stderr)
        return env

    def test_the_temp_home_starts_with_no_marketplace_in_scope(self):
        """Isolation is asserted, not assumed.

        Without this, every row below could be satisfied by the developer's
        pre-existing registration against this repo rather than by the catalog.
        The exit code is asserted first: a listing that FAILED also prints no
        marketplace, and would pass an absence check while proving nothing.
        """
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)

        listed = _harness(env, "marketplace", "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertNotIn("xp-agents", listed.stdout)

    def test_registering_this_repo_surfaces_the_plugin_from_the_catalog(self):
        listed = _harness(self._registered_home(), "list")

        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(
            _PLUGIN_ID,
            listed.stdout,
            "the catalog did not surface the plugin — registration alone is not "
            f"proof of a load. stdout: {listed.stdout}",
        )

    def test_installing_reports_the_version_from_the_manifest_it_pointed_at(self):
        """Install, then read the record back.

        The installed record is read as JSON, which carries the resolved source
        path and the version. Note the listing is only rich AFTER an install —
        before one, `--json` reports empty lists on a home whose text output
        already names the plugin, so this asserts post-install state.
        """
        env = self._registered_home()
        added = _harness(env, "add", _PLUGIN_ID)
        self.assertEqual(added.returncode, 0, added.stderr)

        listed = _harness(env, "list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        entry = _installed_entry(listed)

        manifest = json.loads(
            (_PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(entry["version"], manifest["version"])
        self.assertEqual(
            Path(entry["source"]["path"]).resolve(), _PLUGIN_ROOT.resolve()
        )

    def test_every_shipped_skill_is_discoverable_in_the_installed_tree(self):
        """The COPY, not the source. An install materialises a tree under the
        home; reading the listing's `source.path` back would name the live repo
        and compare it with itself.
        """
        env = self._registered_home()
        added = _harness(env, "add", _PLUGIN_ID)
        self.assertEqual(added.returncode, 0, added.stderr)

        installed_root = _installed_root(added.stdout)
        self.assertTrue(
            installed_root.is_relative_to(Path(env["CODEX_HOME"]).resolve()),
            f"install landed outside the isolated home: {installed_root}",
        )
        skills_dir = installed_root / "skills"
        self.assertTrue(skills_dir.is_dir(), f"install copied no skills: {skills_dir}")

        installed_skills = sorted(p.name for p in skills_dir.iterdir())
        shipped_skills = sorted(p.name for p in (_PLUGIN_ROOT / "skills").iterdir())

        self.assertTrue(shipped_skills, "no skills shipped to compare against")
        self.assertEqual(installed_skills, shipped_skills)


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestWrongSourceFailsTheInstall(unittest.TestCase):
    """The negative that gives the install rows their meaning.

    Built in a throwaway fixture root rather than by editing the shipped catalog:
    registering a local marketplace was measured reporting the live directory as
    its root, so the CATALOG is read in place with no snapshot copy (the plugin
    tree, by contrast, IS copied into the home at install). Mutating the real
    catalog to prove a failure would therefore write to a tracked file, and could
    leave the tree dirty on a crash.
    """

    def test_a_source_path_naming_no_directory_fails_rather_than_installs(self):
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        fixture = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fixture, ignore_errors=True)

        catalog_dir = fixture / ".agents" / "plugins"
        catalog_dir.mkdir(parents=True)
        (catalog_dir / "marketplace.json").write_text(
            json.dumps(
                {
                    "name": "wrong-source",
                    "interface": {"displayName": "Wrong source"},
                    "plugins": [
                        {
                            "name": "xp-agents",
                            "source": {"source": "local", "path": "./nowhere"},
                            "policy": {"installation": "AVAILABLE"},
                            "category": "Developer Tools",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        self.assertEqual(
            _harness(env, "marketplace", "add", str(fixture)).returncode,
            0,
            "registration is expected to succeed — it does not read the source",
        )
        added = _harness(env, "add", "xp-agents@wrong-source")

        self.assertNotEqual(
            added.returncode, 0, f"install should have failed: {added.stdout}"
        )
        self.assertIn("not a directory", (added.stderr + added.stdout).lower())


_GATED_CLASSES = (TestRealRegistrationAndInstall, TestWrongSourceFailsTheInstall)


class TestTheSkipPathIsClean(unittest.TestCase):
    """With no harness on PATH the rows above SKIP — they do not pass.

    The probe itself lives in `_codex_harness`, parameterized on the module and
    its gated classes: `_GATED_CLASSES` names classes local to THIS file, so the
    skip floor cannot be shared as a constant, only derived from what is passed.
    """

    def test_the_module_skips_cleanly_without_the_harness(self):
        assert_module_skips_without_harness(
            self,
            module_path=Path(__file__),
            gated_classes=_GATED_CLASSES,
        )


if __name__ == "__main__":
    unittest.main()
