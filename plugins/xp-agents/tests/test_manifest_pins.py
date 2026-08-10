#!/usr/bin/env python3
"""Pins for the second harness's plugin manifest.

`.claude-plugin/plugin.json` is the hand-edited source of truth.
`scripts/manifest_emit.py` derives `.codex-plugin/plugin.json` from it by
ADDITION — copying every key of the primary untouched and adding exactly
`skills` and `hooks` — and never writes the source. The second manifest is
therefore byte-identical by construction rather than by assertion, which is
what keeps shared metadata (name, version, description) from ever diverging.

Lives at the top level of `tests/` beside the other cross-cutting pins
(`test_hooks_variants.py`, `test_file_size_pin.py`) rather than under a
harness-specific subdirectory, matching where the sibling pin for the hooks
variant lives.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import manifest_emit
from _paths import _PLUGIN_ROOT, _SCRIPTS_DIR

_CLAUDE_MANIFEST = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
_CODEX_MANIFEST = _PLUGIN_ROOT / ".codex-plugin" / "plugin.json"


class TestCodexManifestRegenerationClean(unittest.TestCase):
    """The checked-in derived manifest is exactly what the emitter produces today.

    The anchor pin of this file: everything else asserts a property of the
    artifact, while this one asserts the artifact still equals its derivation.
    Without it the second manifest is just a second hand-maintained manifest.
    """

    def test_emitter_reproduces_the_checked_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            manifest_emit.emit(source=_CLAUDE_MANIFEST, out_dir=out_dir)
            produced = (out_dir / "plugin.json").read_bytes()

        self.assertEqual(
            produced,
            _CODEX_MANIFEST.read_bytes(),
            ".codex-plugin/plugin.json has drifted from the emitter's output — "
            f"re-run `python3 {_SCRIPTS_DIR / 'manifest_emit.py'}` and commit",
        )


class TestSourceIsNeverWritten(unittest.TestCase):
    """The emitter derives; it does not edit its own input.

    Source and target here share the basename `plugin.json` and differ only
    by directory, unlike the hooks emitter where the two names differ within
    one directory. Reproducing the shipped TWO-DIRECTORY layout inside a temp
    tree (rather than pointing both at one temp dir, which would make the
    target BE the source) is what makes this pin assert anything at all. No
    mutation may ever run against the shipped tree.
    """

    def test_emitting_leaves_the_primary_byte_identical_and_writes_only_the_variant(
        self,
    ):
        original = _CLAUDE_MANIFEST.read_bytes()

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            claude_dir = work / ".claude-plugin"
            codex_dir = work / ".codex-plugin"
            claude_dir.mkdir()
            source = claude_dir / "plugin.json"
            source.write_bytes(original)

            manifest_emit.emit(source=source, out_dir=codex_dir)

            self.assertEqual(source.read_bytes(), original, "emitter wrote its source")
            self.assertEqual(
                sorted(p.name for p in codex_dir.iterdir()),
                ["plugin.json"],
                "emitter produced files beyond the variant",
            )

        # And the shipped primary itself is untouched by the run above.
        self.assertEqual(
            _CLAUDE_MANIFEST.read_bytes(), original, "shipped primary was mutated"
        )


if __name__ == "__main__":
    unittest.main()
