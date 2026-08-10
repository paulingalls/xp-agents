#!/usr/bin/env python3
"""Pins for the two repo-root marketplace catalogs.

Each harness discovers the plugin through its own catalog: the first reads
`.claude-plugin/marketplace.json`, the second `.agents/plugins/marketplace.json`.
Only the first existed before this story, so the second harness could not find
the plugin at all — a marketplace registered against this repo listed nothing.

Unlike the two plugin MANIFESTS, these catalogs are not one derived from the
other. They share only the plugin `name`: the top level differs (`owner` vs
`interface`), the source shape differs (a flat path string vs a structured
object), and the second carries `policy` and `category`, which the first has no
counterpart for. So the shared field is pinned rather than generated.

The second catalog's shape was taken from a real 180-entry catalog on disk (the
harness's own curated marketplace), not inferred from prose. What that
measurement does NOT show is enforcement: probing an isolated harness home
found that a nonsense category, a wholly absent `policy` object, and an extra
`description` all load and install without complaint. Pins here therefore
distinguish what the format REQUIRES from what its publisher CONVENTIONALLY
writes, and say which is which.

These pins read JSON and nothing else, so they run everywhere. The proof that
the shape is the one the harness ACCEPTS — a real registration and install —
needs the CLI on PATH and lives in `test_marketplace_install`.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _paths import _PLUGIN_ROOT

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


class TestBothSourcesResolveToThePluginDirectory(unittest.TestCase):
    """Each catalog's source names the directory holding BOTH manifests.

    This is what ties the catalogs to the manifest story: the path is what a
    harness copies and reads a manifest from, so pointing it anywhere else would
    install a tree with no manifest for that harness to load. Both are checked,
    despite only the second being this story's file — the two spell the same
    directory in different shapes (a flat string, a structured object), and a
    rename that fixed one and missed the other is exactly the drift a pin over
    only one would wave through.
    """

    def _resolved(self, raw_path: str) -> Path:
        return (_REPO_ROOT / raw_path.removeprefix("./")).resolve()

    def test_the_first_catalogs_flat_source_resolves_to_the_plugin_directory(self):
        resolved = self._resolved(_entry(_load(_FIRST_CATALOG))["source"])

        self.assertEqual(resolved, _PLUGIN_ROOT.resolve())
        self.assertTrue(resolved.is_dir(), f"{resolved} is not a directory")

    def test_the_second_catalogs_structured_source_resolves_to_the_same_directory(self):
        resolved = self._resolved(_entry(_load(_SECOND_CATALOG))["source"]["path"])

        self.assertEqual(resolved, _PLUGIN_ROOT.resolve())
        self.assertTrue(resolved.is_dir(), f"{resolved} is not a directory")

    def test_the_resolved_directory_holds_both_manifests(self):
        resolved = self._resolved(_entry(_load(_SECOND_CATALOG))["source"]["path"])
        manifests = sorted(
            p.parent.name for p in resolved.glob(".*-plugin/plugin.json")
        )

        self.assertEqual(manifests, [".claude-plugin", ".codex-plugin"], str(manifests))


if __name__ == "__main__":
    unittest.main()
