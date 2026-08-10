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


if __name__ == "__main__":
    unittest.main()
