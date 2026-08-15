#!/usr/bin/env python3
"""Pins for the generated hooks variants — the ARTIFACT, not the rules.

`hooks/hooks.json` is the hand-edited source of truth. `scripts/hooks_emit.py`
derives `hooks/hooks.codex.json` from it and never writes the source. Claude's
variant is therefore byte-identical by construction rather than by assertion,
which is what leaves the fourteen existing suites that read `hooks.json`
untouched.

This file owns the properties of the produced artifact: it regenerates clean,
the emitter's defaults point where they ship, the emitter does not touch its
input, the file parses strict, the CLI works when invoked, and no formatter may
rewrite it. The DERIVATION RULES live beside it, one file per direction:

- `test_hooks_variant_subtraction.py` — events dropped, `timeout`, `async`
- `test_hooks_variant_addition.py` — hook objects the variant carries and the
  source does not

The three-way split was forced rather than stylistic: this file stood at 445
lines against a 500-line cap with the addition rule still to land.

Lives at the top level of `tests/` beside the other cross-cutting pins
(`test_file_size_pin.py`, `test_prose_routing_pin.py`) rather than in
`tests/hooks/`, which holds hook-HANDLER unit tests. It deliberately does not
reuse `tests/hooks/_hooks_json.HooksJsonTestCase`: that base is private to
`tests/hooks/` and loads only the source file, so inheriting it would couple a
packaging pin to a handler-test helper for a two-line `setUp`.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from fnmatch import fnmatch
from pathlib import Path

import tomllib

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import hooks_emit
from _hooks_variant_fixtures import _CODEX, _HOOKS_DIR, _SOURCE, _all_hook_objects
from _paths import _PLUGIN_ROOT, _SCRIPTS_DIR

_RUFF_TOML = _PLUGIN_ROOT.parents[1] / "ruff.toml"


class TestCodexVariantRegenerationClean(unittest.TestCase):
    """The checked-in variant is exactly what the emitter produces today.

    The anchor pin of this file: everything else asserts a property of the
    artifact, while this one asserts the artifact still equals its derivation.
    Without it the generated file is just a second hand-maintained manifest.
    """

    def test_emitter_reproduces_the_checked_in_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            hooks_emit.emit(source=_SOURCE, out_dir=out_dir)
            produced = (out_dir / "hooks.codex.json").read_bytes()

        self.assertEqual(
            produced,
            _CODEX.read_bytes(),
            "hooks.codex.json has drifted from the emitter's output — "
            f"re-run `python3 {_SCRIPTS_DIR / 'hooks_emit.py'}` and commit the result",
        )


class TestEmitterDefaultTarget(unittest.TestCase):
    """The default output directory is the shipped `hooks/` directory.

    Every other pin emits into a tmpdir, so without this one the default the
    emitter actually ships with is exercised only by a human running it — the
    gap plan review recorded as concern 39db2878d085. Asserted as a resolved
    path rather than by writing, so the pin has no side effect on the tree.
    """

    def test_default_out_dir_is_the_shipped_hooks_dir(self):
        self.assertEqual(hooks_emit.default_out_dir(), _HOOKS_DIR)

    def test_default_source_is_the_checked_in_hooks_json(self):
        self.assertEqual(hooks_emit.default_source(), _SOURCE)


class TestSourceIsNeverWritten(unittest.TestCase):
    """The emitter derives; it does not edit its own input.

    This is the property the whole design rests on. Because the first harness's
    manifest is never rewritten, its byte-identity after this story is
    guaranteed by construction rather than by a test, which is what lets the
    fourteen existing suites that read it stay untouched. A pin still earns its
    place: the guarantee is only as good as the emitter continuing to honour it,
    and an "improvement" that normalised both files would be silent.
    """

    def test_emitting_leaves_the_source_byte_identical(self):
        # Re-indented on purpose. The shipped hooks.json is byte-for-byte the
        # emitter's own `json.dumps(..., indent=2) + "\n"`, so a write-back
        # using that call would produce identical bytes and this pin would pass
        # while the property it names was broken. Feeding a copy the emitter
        # would NOT reproduce makes any write-back visible.
        payload = json.loads(_SOURCE.read_text(encoding="utf-8"))
        original = (json.dumps(payload, indent=4) + "\n").encode("utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "hooks.json"
            source.write_bytes(original)

            hooks_emit.emit(source=source, out_dir=work)

            self.assertEqual(source.read_bytes(), original, "emitter wrote its source")

    def test_emitting_creates_only_the_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            # A copy, not the live manifest: every other caller here hands the
            # emitter the checked-in file, so a regression that wrote its source
            # would corrupt the repo from inside the suite that exists to catch it.
            source = work / "source" / "hooks.json"
            source.parent.mkdir()
            source.write_bytes(_SOURCE.read_bytes())
            out_dir = work / "out"
            out_dir.mkdir()

            hooks_emit.emit(source=source, out_dir=out_dir)

            self.assertEqual(
                sorted(p.name for p in out_dir.iterdir()),
                ["hooks.codex.json"],
                "emitter produced files beyond the variant",
            )


class TestVariantIsDerivedBySubtraction(unittest.TestCase):
    """Nothing in the variant was invented — every command comes from the source.

    Cheaper and stronger than re-walking each path to check it exists on disk:
    `TestPluginIntegrity._assert_hook_paths_exist` already proves existence for
    the source, and a subset claim inherits it. It also catches the failure that
    path-existence would miss — a command the emitter synthesised that happens
    to point at a real file.
    """

    def setUp(self):
        self.source = json.loads(_SOURCE.read_text(encoding="utf-8"))
        self.codex = json.loads(_CODEX.read_text(encoding="utf-8"))

    def _commands(self, manifest: dict) -> set[str]:
        return {hook["command"] for _, hook in _all_hook_objects(manifest)}

    def test_variant_commands_are_a_subset_of_the_source(self):
        invented = self._commands(self.codex) - self._commands(self.source)
        self.assertEqual(invented, set(), f"commands not present in source: {invented}")

    def test_every_command_resolves_through_the_plugin_root_variable(self):
        """A relative or absolute path breaks once the host caches the plugin.

        The same rule the shipped hooks.json lives under, asserted on the
        generated file so the emitter cannot rewrite a path into a literal.
        """
        offenders = [
            f"{event}: {hook['command']}"
            for event, hook in _all_hook_objects(self.codex)
            if "${CLAUDE_PLUGIN_ROOT}" not in hook["command"]
        ]
        self.assertEqual(offenders, [], "; ".join(offenders))


class TestVariantParsesStrict(unittest.TestCase):
    """Both manifests must parse as strict JSON.

    Same threat model as `tests/hooks/test_hooks_json_strict.py`, which covers
    the source: a formatter run that introduces a trailing comma produces a file
    the host rejects. `ruff.toml` excludes these paths from formatting; this is
    the symptom check if that guard is ever relaxed.
    """

    def test_codex_variant_parses_strict(self):
        data = json.loads(_CODEX.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        self.assertIn("hooks", data)


class TestEmitterRunsAsASubprocess(unittest.TestCase):
    """E2E: the emitter works when INVOKED, not just when imported.

    Every other pin calls `emit()` in-process, which never exercises the CLI
    entry point, the argument parsing, or the shebang — the form a human or a
    CI step actually uses. An import-only suite would stay green with `main()`
    broken.

    The target directory is deliberately one that does NOT exist yet: both
    emitters document the same `--out-dir` contract, the sibling manifest
    emitter creates its target, and this one died with FileNotFoundError on
    `--out-dir build/hooks` while its documented twin succeeded.
    """

    def test_cli_emits_a_valid_manifest_into_a_target_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "build" / "hooks"
            result = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPTS_DIR / "hooks_emit.py"),
                    "--out-dir",
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            produced = json.loads(
                (out_dir / "hooks.codex.json").read_text(encoding="utf-8")
            )

        self.assertIn("hooks", produced)
        source = json.loads(_SOURCE.read_text(encoding="utf-8"))
        source_commands = {hook["command"] for _, hook in _all_hook_objects(source)}

        for event, hook in _all_hook_objects(produced):
            with self.subTest(event=event):
                self.assertIn(hook["command"], source_commands)
                self.assertIn("${CLAUDE_PLUGIN_ROOT}", hook["command"])


class TestFormatterExclusionCoversEveryManifest(unittest.TestCase):
    """The strict-JSON guard must cover EVERY hook manifest, not just the first.

    `ruff.toml` carries `extend-exclude` plus `force-exclude = true` so that an
    ad-hoc `ruff format .` — or a path passed explicitly — cannot rewrite a hook
    manifest and introduce a trailing comma the host then rejects.

    Stated over the DIRECTORY rather than over today's two filenames, so a
    third manifest is covered the day it appears rather than silently omitted.
    """

    def setUp(self):
        self.config = tomllib.loads(_RUFF_TOML.read_text(encoding="utf-8"))
        self.patterns = self.config.get("extend-exclude", [])
        self.assertTrue(self.patterns, "ruff.toml declares no extend-exclude")

    def _is_excluded(self, name: str) -> bool:
        # ruff matches globs against the path; a leading `**/` makes the
        # pattern basename-relative, which is how every entry here is written.
        return any(
            fnmatch(name, pattern.removeprefix("**/")) for pattern in self.patterns
        )

    def test_every_hook_manifest_is_excluded_from_formatting(self):
        manifests = sorted(p.name for p in _HOOKS_DIR.glob("*.json"))
        self.assertTrue(manifests, "no hook manifests found to check")
        unguarded = [name for name in manifests if not self._is_excluded(name)]
        self.assertEqual(
            unguarded,
            [],
            f"hook manifests outside ruff's exclude: {unguarded}. A formatter "
            "run can introduce a trailing comma and the host rejects the file.",
        )

    def test_force_exclude_stays_on(self):
        """Without it the exclude is ignored for explicitly-passed paths."""
        self.assertIs(self.config.get("force-exclude"), True)


if __name__ == "__main__":
    unittest.main()
