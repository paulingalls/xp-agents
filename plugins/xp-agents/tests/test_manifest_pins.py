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

import json
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

    def test_hooks_field_names_the_generated_second_variant_explicitly(self):
        """A component key REPLACES default discovery on the second harness.

        Omitting `hooks` there would not fall back to nothing — it would load
        the FIRST harness's `hooks.json`, registering every handler against a
        manifest built for the other harness.
        """
        codex = json.loads(_CODEX_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(codex["hooks"], "./hooks/hooks.codex.json")

        hooks_path = _CODEX_MANIFEST.parent.parent / "hooks" / "hooks.codex.json"
        self.assertTrue(
            hooks_path.is_file(), f"{hooks_path} named by the manifest does not exist"
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


class TestEmitRefusesToOverwriteItsSource(unittest.TestCase):
    """`emit()` raises rather than overwrite the hand-edited primary.

    Source and target share the basename `plugin.json` and differ only by
    directory, so an `--out-dir` equal to the source's own directory would
    silently replace the hand-edited primary with generated content. This is
    the enforced guarantee the milestone's plan review flagged as its
    highest-severity finding.
    """

    def test_emit_raises_when_out_dir_resolves_to_the_source_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = Path(tmp) / ".claude-plugin"
            claude_dir.mkdir()
            source = claude_dir / "plugin.json"
            source.write_bytes(_CLAUDE_MANIFEST.read_bytes())

            with self.assertRaises(ValueError):
                manifest_emit.emit(source=source, out_dir=claude_dir)

            # And the source itself was not touched by the attempt.
            self.assertEqual(source.read_bytes(), _CLAUDE_MANIFEST.read_bytes())


class TestEmitterDefaultTargets(unittest.TestCase):
    """The emitter's default source and out_dir are the two shipped directories.

    Every other pin here passes explicit paths, so without this one the
    defaults the emitter actually ships with — the ones a bare
    `python3 manifest_emit.py` uses — are exercised only by a human running it.
    """

    def test_default_source_is_the_checked_in_claude_manifest(self):
        self.assertEqual(manifest_emit.default_source(), _CLAUDE_MANIFEST)

    def test_default_out_dir_is_the_shipped_codex_plugin_dir(self):
        self.assertEqual(manifest_emit.default_out_dir(), _CODEX_MANIFEST.parent)

    def test_defaults_are_two_distinct_directories(self):
        self.assertNotEqual(
            manifest_emit.default_source().parent, manifest_emit.default_out_dir()
        )


class TestSharedMetadataIsIdentical(unittest.TestCase):
    """`name`, `version` and `description` must agree across both manifests.

    The story's whole reason to derive rather than hand-write: shared metadata
    holds by construction because the second manifest copies the primary, but
    a copy step can still be edited into dropping a key, so the property is
    pinned directly rather than left to follow from
    `TestCodexManifestRegenerationClean`.
    """

    _SHARED_KEYS = ("name", "version", "description")

    def setUp(self):
        self.claude = json.loads(_CLAUDE_MANIFEST.read_text(encoding="utf-8"))
        self.codex = json.loads(_CODEX_MANIFEST.read_text(encoding="utf-8"))

    def test_all_shared_keys_are_present_in_both_manifests(self):
        """Non-vacuity guard: two absent keys would otherwise compare equal.

        Without this, a manifest missing `version` entirely would satisfy the
        equality pin below by both sides being `None` — asserting nothing
        about the property the milestone actually requires.
        """
        for key in self._SHARED_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, self.claude, f"primary manifest is missing {key!r}")
                self.assertIn(key, self.codex, f"derived manifest is missing {key!r}")

    def test_shared_metadata_matches(self):
        for key in self._SHARED_KEYS:
            with self.subTest(key=key):
                self.assertEqual(self.claude[key], self.codex[key])


class TestNoSubagentsShippingKey(unittest.TestCase):
    """Neither manifest declares an `agents` key — for two DIFFERENT reasons.

    On the second harness, an `agents` key is accepted and SILENTLY IGNORED:
    measured by installing `"agents": "./agents/"` and reading the plugin
    back — no `agents` key surfaced at all, while `skills` and `hooks` did.
    Declaring it there would therefore be harmless but pointless.

    On the first harness, `agents` IS honoured and REPLACES the default
    `agents/` directory scan. Declaring it there would be a live behaviour
    change, not a no-op — the opposite risk from the second harness's.

    Neither rationale is true of both manifests; this pin's docstring exists
    so a future edit doesn't collapse the two reasons into one.
    """

    def test_claude_manifest_declares_no_agents_key(self):
        claude = json.loads(_CLAUDE_MANIFEST.read_text(encoding="utf-8"))
        self.assertNotIn("agents", claude)

    def test_codex_manifest_declares_no_agents_key(self):
        codex = json.loads(_CODEX_MANIFEST.read_text(encoding="utf-8"))
        self.assertNotIn("agents", codex)


if __name__ == "__main__":
    unittest.main()
