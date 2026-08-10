#!/usr/bin/env python3
"""Pins for the two repo-root marketplace catalogs.

Each harness discovers the plugin through its own catalog: the first reads
`.claude-plugin/marketplace.json`, the second `.agents/plugins/marketplace.json`.
Only the first existed before this story, so the second harness could not find
the plugin at all — a marketplace registered against this repo listed nothing.

Unlike the two plugin MANIFESTS, these catalogs are not one derived from the
other. They share only the plugin `name`: the top level differs (`owner` vs
`interface`), the source shape differs (a flat path string vs a structured
object), and the second carries three keys with no counterpart in the first. So
the shared field is pinned rather than generated.

The second catalog's shape was taken from a real 180-entry catalog on disk (the
harness's own curated marketplace), not inferred from prose. What that
measurement does NOT show is enforcement: probing an isolated harness home
found that a nonsense category, a wholly absent `policy` object, and an extra
`description` all load and install without complaint. Pins here therefore
distinguish what the format REQUIRES from what its publisher CONVENTIONALLY
writes, and say which is which.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _paths import _PLUGIN_ROOT

_HARNESS = "codex"

_REPO_ROOT = _PLUGIN_ROOT.parents[1]
_FIRST_CATALOG = _REPO_ROOT / ".claude-plugin" / "marketplace.json"
_SECOND_CATALOG = _REPO_ROOT / ".agents" / "plugins" / "marketplace.json"

# The 11 categories the reference catalog uses. A CONVENTION, not a rule: a
# nonsense category was measured installing cleanly, so this pin exists to keep
# our entry inside the observed vocabulary, not because the harness checks.
_OBSERVED_CATEGORIES = frozenset(
    {
        "Business & Operations",
        "Communication",
        "Creativity",
        "Data & Analytics",
        "Developer Tools",
        "Education & Research",
        "Finance",
        "Other",
        "Productivity",
        "Security",
        "Travel",
    }
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _entry(catalog: dict, name: str = "xp-agents") -> dict:
    """The named plugin entry, or fail loudly rather than return a default.

    A missing entry must not read as an empty dict whose fields then compare
    equal to another empty dict — that is how a cross-catalog pin passes while
    proving nothing.
    """
    for plugin in catalog.get("plugins", []):
        if plugin.get("name") == name:
            return plugin
    raise AssertionError(f"no {name!r} entry in catalog: {catalog.get('plugins')}")


class TestBothCatalogsParse(unittest.TestCase):
    """Each catalog is valid JSON carrying the fields its own harness reads."""

    def test_first_catalog_parses_with_its_required_fields(self):
        catalog = _load(_FIRST_CATALOG)
        self.assertEqual(catalog["name"], "xp-agents")
        self.assertIn("owner", catalog)
        entry = _entry(catalog)
        self.assertIsInstance(entry["source"], str)
        self.assertTrue(entry["description"])

    def test_second_catalog_parses_with_its_required_fields(self):
        catalog = _load(_SECOND_CATALOG)
        self.assertEqual(catalog["name"], "xp-agents")
        self.assertTrue(catalog["interface"]["displayName"])
        entry = _entry(catalog)
        self.assertEqual(entry["source"]["source"], "local")
        self.assertTrue(entry["source"]["path"])
        self.assertEqual(entry["policy"]["installation"], "AVAILABLE")


class TestSharedNameMatchesEverywhere(unittest.TestCase):
    """The plugin name agrees across EVERY catalog in the tree, not just the two.

    A third catalog sits inside the plugin directory, identical to the repo-root
    one except its `source` (`./` rather than `./plugins/xp-agents`) — it exists
    so the plugin directory can serve as its own marketplace root. Nothing in
    this story writes to it, but a name that drifted there would be just as
    wrong, so the sweep is over every `marketplace.json` on disk. Reading them
    all is in scope precisely because reading is not writing.
    """

    def _catalogs(self) -> list[Path]:
        found = sorted(
            p
            for p in _REPO_ROOT.rglob("marketplace.json")
            if ".git" not in p.parts and "node_modules" not in p.parts
        )
        self.assertGreaterEqual(
            len(found),
            3,
            f"expected at least the three known catalogs, found {found}",
        )
        return found

    def test_every_catalog_declares_the_same_marketplace_and_plugin_name(self):
        for path in self._catalogs():
            with self.subTest(catalog=path.relative_to(_REPO_ROOT)):
                catalog = _load(path)
                self.assertIn("name", catalog, "catalog declares no marketplace name")
                self.assertEqual(catalog["name"], "xp-agents")
                entry = _entry(catalog)
                self.assertIn("name", entry, "plugin entry declares no name")
                self.assertEqual(entry["name"], "xp-agents")


class TestSecondCatalogCarriesNoDescription(unittest.TestCase):
    """This catalog carries no description — an observation, not a schema rule.

    Zero of the reference catalog's 180 entries carry one, and `interface` has
    no home for it either, so there is nowhere for the first catalog's
    description to go. But an extra `description` was measured loading and
    installing cleanly, so the format does not REJECT one. The claim pinned here
    is therefore about this file, not about the format: we do not ship a field
    whose only evidence is that nothing complained about it — the same call the
    manifest story made when it refused to ship an accepted-and-ignored key.
    """

    def test_the_entry_declares_no_description(self):
        self.assertNotIn("description", _entry(_load(_SECOND_CATALOG)))

    def test_the_first_catalog_still_has_one_to_lose(self):
        """Control. Without it, a first catalog that dropped its own description
        would make the asymmetry above vacuously true."""
        self.assertTrue(_entry(_load(_FIRST_CATALOG))["description"])


class TestCategoryIsFromTheObservedVocabulary(unittest.TestCase):
    """`category` sits inside the publisher's observed set — a convention.

    Measured: a nonsense category installs without complaint, so nothing in the
    harness enforces this. The pin keeps our entry inside the vocabulary a user
    browsing the marketplace would recognise.
    """

    def test_category_is_one_of_the_observed_values(self):
        self.assertIn(_entry(_load(_SECOND_CATALOG))["category"], _OBSERVED_CATEGORIES)


class TestStructuredSourceResolves(unittest.TestCase):
    """The structured source path names the directory holding BOTH manifests.

    This is what ties the catalog to the manifest story: the path is what the
    harness copies and reads a manifest from, so pointing it anywhere else would
    install a tree with no manifest for that harness to load.
    """

    def test_the_source_path_resolves_to_the_plugin_directory(self):
        entry = _entry(_load(_SECOND_CATALOG))
        resolved = (_REPO_ROOT / entry["source"]["path"].removeprefix("./")).resolve()

        self.assertEqual(resolved, _PLUGIN_ROOT.resolve())
        self.assertTrue(resolved.is_dir(), f"{resolved} is not a directory")

    def test_the_resolved_directory_holds_both_manifests(self):
        entry = _entry(_load(_SECOND_CATALOG))
        resolved = (_REPO_ROOT / entry["source"]["path"].removeprefix("./")).resolve()
        manifests = sorted(
            p.parent.name for p in resolved.glob(".*-plugin/plugin.json")
        )

        self.assertEqual(manifests, [".claude-plugin", ".codex-plugin"], str(manifests))


def _isolated_home() -> tuple[dict, Path]:
    """An environment whose harness state is a fresh temp directory.

    Every harness invocation in this file runs under one of these. The user's
    real config already carries a marketplace registered against this very repo
    (left by the packaging spike), so without isolation a passing install could
    be satisfied by that standing registration instead of by the catalog under
    test — and worse, the suite would mutate the developer's own state.
    """
    home = Path(tempfile.mkdtemp())
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    return env, home


def _harness(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_HARNESS, "plugin", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestRealRegistrationAndInstall(unittest.TestCase):
    """The catalog is proven by a real registration and install, not by schema.

    Registration alone proves nothing: `marketplace add` was measured returning
    zero against this repo while the catalog did not exist at all. So the load is
    asserted from the listing, and the install from reading the plugin back.
    """

    @classmethod
    def setUpClass(cls):
        cls.env, cls.home = _isolated_home()
        cls.addClassCleanup(shutil.rmtree, cls.home, ignore_errors=True)

    def test_the_temp_home_starts_with_no_marketplace_in_scope(self):
        """Isolation is asserted, not assumed.

        Without this, every row below could be satisfied by the developer's
        pre-existing registration against this repo rather than by the catalog.
        """
        listed = _harness(self.env, "marketplace", "list")
        self.assertNotIn("xp-agents", listed.stdout)

    def test_registering_this_repo_surfaces_the_plugin_from_the_catalog(self):
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)

        added = _harness(env, "marketplace", "add", str(_REPO_ROOT))
        self.assertEqual(added.returncode, 0, added.stderr)

        listed = _harness(env, "list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(
            "xp-agents@xp-agents",
            listed.stdout,
            "the catalog did not surface the plugin — registration alone is not "
            f"proof of a load. stdout: {listed.stdout}",
        )

    def test_installing_reports_the_version_from_the_manifest_it_pointed_at(self):
        """AC#3 and AC#5 together: install, then read the record back.

        The installed record is read as JSON, which carries the resolved source
        path and the version. Note the listing is only rich AFTER an install —
        before one, `--json` reports empty lists on a home whose text output
        already names the plugin, so this asserts post-install state.
        """
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertEqual(
            _harness(env, "marketplace", "add", str(_REPO_ROOT)).returncode, 0
        )

        added = _harness(env, "add", "xp-agents@xp-agents")
        self.assertEqual(added.returncode, 0, added.stderr)

        listed = _harness(env, "list", "--json")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        installed = json.loads(listed.stdout)["installed"]
        entry = next(e for e in installed if e["pluginId"] == "xp-agents@xp-agents")

        manifest = json.loads(
            (_PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertEqual(entry["version"], manifest["version"])
        self.assertEqual(
            Path(entry["source"]["path"]).resolve(), _PLUGIN_ROOT.resolve()
        )

    def test_every_shipped_skill_is_discoverable_in_the_installed_tree(self):
        env, home = _isolated_home()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertEqual(
            _harness(env, "marketplace", "add", str(_REPO_ROOT)).returncode, 0
        )
        self.assertEqual(_harness(env, "add", "xp-agents@xp-agents").returncode, 0)

        listed = json.loads(_harness(env, "list", "--json").stdout)["installed"]
        entry = next(e for e in listed if e["pluginId"] == "xp-agents@xp-agents")
        installed_skills = sorted(
            p.name for p in (Path(entry["source"]["path"]) / "skills").iterdir()
        )
        shipped_skills = sorted(p.name for p in (_PLUGIN_ROOT / "skills").iterdir())

        self.assertTrue(shipped_skills, "no skills shipped to compare against")
        self.assertEqual(installed_skills, shipped_skills)


@unittest.skipUnless(
    shutil.which(_HARNESS), f"{_HARNESS} not on PATH — install-dependent rows skip"
)
class TestWrongSourceFailsTheInstall(unittest.TestCase):
    """The negative that gives the install rows their meaning.

    Built in a throwaway fixture root rather than by editing the shipped catalog:
    a local marketplace's `installedRoot` was measured to be the live directory,
    with no snapshot copy, so mutating the real catalog to prove a failure would
    write to a tracked file and could leave the tree dirty on a crash.
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


_INNER_RUN = "XP_MARKETPLACE_SKIP_PROBE"


@unittest.skipIf(
    os.environ.get(_INNER_RUN),
    "inner run of the skip probe — it re-executes this module, so without this "
    "guard the probe would spawn itself without end",
)
class TestTheSkipPathIsClean(unittest.TestCase):
    """With no harness on PATH the install rows SKIP — they do not pass.

    The claim needs its own check because this machine has the harness, so the
    skip branch never runs here. A decorator that silently took the pass branch
    would look identical in a green suite; running the module with the harness
    stripped from PATH is what tells the two apart.

    The inner run is marked with an environment sentinel and this class skips
    itself there. Written without it, the probe re-entered its own module and
    recursed until the run was killed — the guard is load-bearing, not tidiness.
    """

    def test_the_module_skips_cleanly_without_the_harness(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)

        env = os.environ.copy()
        env[_INNER_RUN] = "1"
        # An EMPTY PATH rather than one filtered of directories containing the
        # harness: the harness shares a directory with the test runner here, so
        # filtering would strip the runner too. The inner run needs no PATH at
        # all — it is launched through sys.executable.
        env["PATH"] = str(empty)
        self.assertIsNone(
            shutil.which(_HARNESS, path=env["PATH"]),
            "the harness is still reachable, so the inner run would take the "
            "RUN branch and prove nothing about skipping",
        )

        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(Path(__file__)), "-q", "--no-header"],
            capture_output=True,
            text=True,
            env=env,
            cwd=_REPO_ROOT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout[-2000:])
        self.assertRegex(
            result.stdout,
            r"\d+ skipped",
            "the install rows did not report as skipped — a harness-free run "
            f"must skip them, never quietly pass. stdout: {result.stdout[-2000:]}",
        )


if __name__ == "__main__":
    unittest.main()
