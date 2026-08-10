#!/usr/bin/env python3
"""Pins for `plugin_loader.plugin_version` choosing the EXECUTING manifest.

The defect this file exists for was measured: the version read hardcoded one
manifest path, so a session reported one number while the version-keyed cache
directory it actually executed from held another. The number is the only thing
identifying which cached copy is running.

Two manifests now ship (the second generated from the first), so they agree by
construction and "which manifest" is invisible in the return value of a
correctly built tree. The signal that remains — and the one the spike actually
measured — is agreement between a manifest and the PATH of the copy executing.
Every fixture here therefore builds a root whose directory NAME is the version
segment, and makes the two manifests disagree, because agreeing manifests cannot
show which one was chosen.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import plugin_loader

_UNKNOWN = "?"


def _write_manifest(root: Path, dirname: str, payload: object) -> None:
    """Write `payload` as `<root>/<dirname>/plugin.json`.

    `payload` is dumped as JSON when it is a mapping, and written verbatim when
    it is a string — that is how the malformed-manifest rows produce a file that
    exists but cannot be parsed.
    """
    manifest_dir = root / dirname
    manifest_dir.mkdir(parents=True, exist_ok=True)
    target = manifest_dir / "plugin.json"
    if isinstance(payload, str):
        target.write_text(payload, encoding="utf-8")
    else:
        target.write_text(json.dumps(payload), encoding="utf-8")


class _FixtureRootTestCase(unittest.TestCase):
    """Builds a plugin root under a directory named for the executing version.

    The root's own directory name is the version-keyed path segment, mirroring
    the shipped cache layout (`.../xp-agents/xp-agents/5.12.0`) without
    asserting the segment's position — the production code scans components
    rather than indexing them.
    """

    def _root(self, segment: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / segment
        root.mkdir(parents=True)
        return root

    def _version_at(self, root: Path) -> str:
        """`plugin_version()` as read from `root`, via the env var readers use."""
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": str(root)}):
            return plugin_loader.plugin_version()


class TestExecutingCopyWins(_FixtureRootTestCase):
    """The version-shaped path component picks the manifest, not a fixed name.

    Both orientations are pinned deliberately. With only the first row, an
    implementation that simply preferred the SECOND manifest would pass — which
    is the shipped defect inverted, not a fix. The pair is what makes either row
    mean anything.
    """

    def test_second_manifest_wins_when_the_path_names_its_version(self):
        root = self._root("9.9.9")
        _write_manifest(root, ".claude-plugin", {"version": "1.0.0"})
        _write_manifest(root, ".codex-plugin", {"version": "9.9.9"})

        self.assertEqual(self._version_at(root), "9.9.9")

    def test_primary_manifest_wins_when_the_path_names_its_version(self):
        root = self._root("9.9.9")
        _write_manifest(root, ".claude-plugin", {"version": "9.9.9"})
        _write_manifest(root, ".codex-plugin", {"version": "1.0.0"})

        self.assertEqual(self._version_at(root), "9.9.9")

    def test_the_measured_case(self):
        """The spike's own numbers, as a regression row.

        Cache directory `5.3.13`, second manifest `5.3.13`, primary `5.5.0`. The
        shipped code returned `5.5.0` — the copy that was NOT executing.
        """
        root = self._root("5.3.13")
        _write_manifest(root, ".claude-plugin", {"version": "5.5.0"})
        _write_manifest(root, ".codex-plugin", {"version": "5.3.13"})

        self.assertEqual(self._version_at(root), "5.3.13")


class TestNoVersionShapedComponent(_FixtureRootTestCase):
    """An ordinary checkout has no version key in its path.

    This is the row that keeps local development and the shipped banner E2E
    working: the repo path carries no version-shaped component, so without it
    every local run would degrade to the unknown marker.
    """

    def test_agreeing_manifests_give_their_agreed_version(self):
        root = self._root("checkout")
        _write_manifest(root, ".claude-plugin", {"version": "5.12.0"})
        _write_manifest(root, ".codex-plugin", {"version": "5.12.0"})

        self.assertEqual(self._version_at(root), "5.12.0")

    def test_disagreeing_manifests_give_the_unknown_marker(self):
        """No evidence for either candidate, so neither is preferred."""
        root = self._root("checkout")
        _write_manifest(root, ".claude-plugin", {"version": "1.0.0"})
        _write_manifest(root, ".codex-plugin", {"version": "9.9.9"})

        self.assertEqual(self._version_at(root), _UNKNOWN)

    def test_an_ordinary_numeric_directory_is_not_a_version_key(self):
        """`2` is a directory name, not a cache key.

        The version shape is narrow for this reason: read loosely, a checkout
        under any numeric directory would report unknown.
        """
        root = self._root("2")
        _write_manifest(root, ".claude-plugin", {"version": "5.12.0"})
        _write_manifest(root, ".codex-plugin", {"version": "5.12.0"})

        self.assertEqual(self._version_at(root), "5.12.0")


class TestVersionShapedComponentMatchingNothing(_FixtureRootTestCase):
    """A version key naming no manifest is REPORTED, not smoothed over.

    This is the cache-bumped-in-place state the spike records: files get
    injected into an already-cached copy, so a bump without a reinstall leaves
    the directory key and the manifests disagreeing. Returning the manifests'
    number there would be a confident wrong answer about which copy is running,
    which is the whole defect this story removes.
    """

    def test_disagreeing_manifests_give_the_unknown_marker(self):
        root = self._root("7.7.7")
        _write_manifest(root, ".claude-plugin", {"version": "1.0.0"})
        _write_manifest(root, ".codex-plugin", {"version": "9.9.9"})

        self.assertEqual(self._version_at(root), _UNKNOWN)

    def test_even_agreeing_manifests_give_the_unknown_marker(self):
        """The sharp row. Both manifests say 5.5.0 and the path says 7.7.7.

        An implementation that fell back to "they agree, so use it" would pass
        every other row in this file and still report a version that is not the
        executing copy's.
        """
        root = self._root("7.7.7")
        _write_manifest(root, ".claude-plugin", {"version": "5.5.0"})
        _write_manifest(root, ".codex-plugin", {"version": "5.5.0"})

        self.assertEqual(self._version_at(root), _UNKNOWN)


class TestUnreadableManifests(_FixtureRootTestCase):
    """A manifest that exists but cannot be read is a failure to report.

    Dropping it and using a readable sibling would silently change today's
    answer for a malformed primary from unknown to some other number — a
    regression in honesty dressed as robustness. So an unreadable manifest makes
    the survey incomplete, which blocks the agreement shortcut but not path
    attribution, since attribution rests on positive evidence from a manifest
    that WAS read.
    """

    def test_a_sole_malformed_manifest_gives_the_unknown_marker(self):
        root = self._root("checkout")
        _write_manifest(root, ".claude-plugin", "{not valid json")

        self.assertEqual(self._version_at(root), _UNKNOWN)

    def test_a_manifest_without_a_version_key_gives_the_unknown_marker(self):
        root = self._root("checkout")
        _write_manifest(root, ".claude-plugin", {"name": "xp-agents"})

        self.assertEqual(self._version_at(root), _UNKNOWN)

    def test_malformed_primary_blocks_the_agreement_shortcut(self):
        """Incomplete survey plus no path signal: refuse rather than substitute."""
        root = self._root("checkout")
        _write_manifest(root, ".claude-plugin", "{not valid json")
        _write_manifest(root, ".codex-plugin", {"version": "9.9.9"})

        self.assertEqual(self._version_at(root), _UNKNOWN)

    def test_malformed_primary_does_not_block_path_attribution(self):
        """Positive evidence stands: the path names the readable manifest."""
        root = self._root("9.9.9")
        _write_manifest(root, ".claude-plugin", "{not valid json")
        _write_manifest(root, ".codex-plugin", {"version": "9.9.9"})

        self.assertEqual(self._version_at(root), "9.9.9")

    def test_no_manifest_at_all_gives_the_unknown_marker(self):
        self.assertEqual(self._version_at(self._root("checkout")), _UNKNOWN)


class TestSingleManifest(_FixtureRootTestCase):
    """One manifest is the shipped shape of an already-cached older copy.

    Verified while planning: the live installed cache holds only the primary,
    because it was released before the second manifest existed. A read that
    needed two manifests would answer unknown for every currently-installed
    copy.
    """

    def test_a_single_manifest_named_by_the_path_is_used(self):
        root = self._root("5.12.0")
        _write_manifest(root, ".claude-plugin", {"version": "5.12.0"})

        self.assertEqual(self._version_at(root), "5.12.0")

    def test_a_single_manifest_with_no_path_signal_is_used(self):
        root = self._root("checkout")
        _write_manifest(root, ".claude-plugin", {"version": "5.12.0"})

        self.assertEqual(self._version_at(root), "5.12.0")


class TestTheReadIsUncached(_FixtureRootTestCase):
    """Two roots in one process must give two answers.

    The story's interface contract calls this out: memoizing an env-dependent
    resolution breaks isolation in source-order test runners, and a previous
    lru_cache on the root resolver did exactly that. The guide loaders already
    pin the property; this extends it to the version read.
    """

    def test_a_changed_plugin_root_changes_the_answer(self):
        first = self._root("1.2.3")
        _write_manifest(first, ".claude-plugin", {"version": "1.2.3"})
        second = self._root("4.5.6")
        _write_manifest(second, ".claude-plugin", {"version": "4.5.6"})

        self.assertEqual(self._version_at(first), "1.2.3")
        self.assertEqual(self._version_at(second), "4.5.6")


if __name__ == "__main__":
    unittest.main()
