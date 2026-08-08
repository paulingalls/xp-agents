#!/usr/bin/env python3
"""Pins for the generated hooks variants.

`hooks/hooks.json` is the hand-edited source of truth. `scripts/hooks_emit.py`
derives `hooks/hooks.codex.json` from it by SUBTRACTION — dropping events the
second harness does not recognise, every `timeout`, and every `async` — and
never writes the source. Claude's variant is therefore byte-identical by
construction rather than by assertion, which is what leaves the fourteen
existing suites that read `hooks.json` untouched.

Both files are checked in. These pins fail if the generated one drifts from
what the emitter produces, so the pair cannot rot apart.

Lives at the top level of `tests/` beside the other cross-cutting pins
(`test_file_size_pin.py`, `test_prose_routing_pin.py`) rather than in
`tests/hooks/`, which holds hook-HANDLER unit tests. It deliberately does not
reuse `tests/hooks/_hooks_json.HooksJsonTestCase`: that base is private to
`tests/hooks/` and loads only the source file, so inheriting it would couple a
packaging pin to a handler-test helper for a two-line `setUp`.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from _paths import _PLUGIN_ROOT, _SCRIPTS_DIR

_HOOKS_DIR = _PLUGIN_ROOT / "hooks"
_SOURCE = _HOOKS_DIR / "hooks.json"
_CODEX = _HOOKS_DIR / "hooks.codex.json"


class TestCodexVariantRegenerationClean(unittest.TestCase):
    """The checked-in variant is exactly what the emitter produces today.

    The anchor pin of this file: everything else asserts a property of the
    artifact, while this one asserts the artifact still equals its derivation.
    Without it the generated file is just a second hand-maintained manifest.
    """

    def test_emitter_reproduces_the_checked_in_variant(self):
        import hooks_emit

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
        import hooks_emit

        self.assertEqual(hooks_emit.default_out_dir(), _HOOKS_DIR)

    def test_default_source_is_the_checked_in_hooks_json(self):
        import hooks_emit

        self.assertEqual(hooks_emit.default_source(), _SOURCE)


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


if __name__ == "__main__":
    unittest.main()
