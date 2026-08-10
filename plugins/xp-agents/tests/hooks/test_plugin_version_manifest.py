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


if __name__ == "__main__":
    unittest.main()
