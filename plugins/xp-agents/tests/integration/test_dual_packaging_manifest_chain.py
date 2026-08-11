#!/usr/bin/env python3
"""Milestone 8 capstone, hermetic half: the manifest names what the emitter wrote.

Split from `test_dual_packaging_e2e.py` — which carries the harness-dependent
half (install, then the version read from inside the installed copy) — when the
combined file reached three lines below the per-file band floor. Sitting just
under a limit is the shape that produced the same debt four times in this repo,
so the seam is the natural one: everything here is hermetic and always runs,
while everything there needs the CLI on PATH and skips without it.

## The seam this closes

`test_manifest_pins.py` is the closest existing row, and it hardcodes the hooks
path twice: once as the value it expects the manifest to carry, and again as a
path it rebuilds from its own constants to check that a file is there. It never
reads `codex["hooks"]` to decide WHICH file to look for. So changing the
emitter's declared path to a typo and updating the expected literal to match —
the natural way to "fix the failing test" — leaves every pin green while the
shipped manifest names a file that does not exist. The name is written down
independently in each emitter — `manifest_emit.transform()` declares the path,
`hooks_emit._VARIANT_NAME` names the file — with nothing tying the two together,
and every pin that reads them carries its own literal rather than closing that
gap.

This module compares two DERIVED values with no literal on either side: the path
the manifest declares, resolved against its own plugin root, against the path the
hooks emitter returns.
"""

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import hooks_emit
import manifest_emit
from _bases import _PLUGIN_ROOT, _AssertNotNoneMixin


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _fixture_plugin_root(case: unittest.TestCase) -> Path:
    """A throwaway plugin root holding only the two hand-edited source specs.

    A fixture rather than the shipped tree because the emitters WRITE, and no
    mutation may ever run against the tree that ships. The hooks source carries
    one event the second harness does not recognise, so the derived variant's
    event set is a STRICT subset of it — which is what makes the subset assertion
    below say something.
    """
    root = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, root, ignore_errors=True)

    _write_json(
        root / ".claude-plugin" / "plugin.json",
        {
            "name": "fixture-plugin",
            "version": "9.9.9",
            "description": "a throwaway source spec, never shipped",
        },
    )
    _write_json(
        root / "hooks" / "hooks.json",
        {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 ${CLAUDE_PLUGIN_ROOT}/x.py",
                                "timeout": 5,
                            }
                        ],
                    }
                ],
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [
                            {"type": "command", "command": "python3 y.py"},
                        ],
                    }
                ],
                # Recognised by the first harness only; the emitter subtracts it.
                "PreCompact": [
                    {"hooks": [{"type": "command", "command": "python3 z.py"}]}
                ],
            }
        },
    )
    return root


def _regenerate(root: Path) -> tuple[Path, Path]:
    """Run both emitters over *root*; return (derived manifest, produced variant).

    Both return the path they wrote, which is the whole point: the comparison
    downstream asks each emitter where its output went instead of assuming.
    """
    derived = manifest_emit.emit(
        source=root / ".claude-plugin" / "plugin.json",
        out_dir=root / ".codex-plugin",
    )
    produced = hooks_emit.emit(
        source=root / "hooks" / "hooks.json", out_dir=root / "hooks"
    )
    return derived, produced


def _declared_hooks_path(manifest: Path, root: Path) -> Path:
    """The hooks file a manifest DECLARES, resolved against its plugin root.

    Reading `hooks` out of the manifest is the load-bearing part. A check that
    rebuilds the path from its own constants tests that some file exists, not
    that the manifest points at it.
    """
    declared = json.loads(manifest.read_text(encoding="utf-8"))["hooks"]
    return (root / declared).resolve()


class TestTheManifestNamesTheFileTheEmitterProduces(unittest.TestCase):
    """Link one of the chain: story-002's manifest against story-001's variant."""

    def test_the_declared_hooks_path_is_the_path_the_emitter_wrote(self):
        root = _fixture_plugin_root(self)
        derived, produced = _regenerate(root)

        self.assertEqual(
            _declared_hooks_path(derived, root),
            produced.resolve(),
            "the manifest's declared hooks path is not the file the hooks "
            "emitter produced — the two carry independent copies of that name",
        )

    def test_a_manifest_naming_another_file_is_reported_as_a_mismatch(self):
        """The negative control, through the SAME resolver the row above uses.

        Without it, that row shows only that two functions agree with each other
        today; it would keep passing if the resolver silently returned the
        emitter's own answer. Here the manifest is rewritten to name a sibling
        the emitter never wrote, and the mismatch has to surface.
        """
        root = _fixture_plugin_root(self)
        derived, produced = _regenerate(root)

        payload = json.loads(derived.read_text(encoding="utf-8"))
        payload["hooks"] = "./hooks/hooks.other.json"
        _write_json(derived, payload)

        wrong = _declared_hooks_path(derived, root)
        self.assertNotEqual(wrong, produced.resolve())
        self.assertFalse(
            wrong.is_file(), f"the fixture named a file that exists: {wrong}"
        )

    def test_the_named_file_parses_as_a_hooks_manifest(self):
        """AC#2's second clause: it names a hooks manifest, not merely a file.

        No event COUNT is asserted. Eight is the shipped variant's number (14
        source events less the 6 unrecognised), unreachable from a hand-built
        fixture; writing it would either force this fixture to mirror the shipped
        source — breaking the capstone whenever a hook event is added — or bake in
        a number that means nothing here. The subset relation is derived from the
        fixture instead, and proving the subtraction itself is story-001's job.
        """
        root = _fixture_plugin_root(self)
        derived, _ = _regenerate(root)

        variant = json.loads(
            _declared_hooks_path(derived, root).read_text(encoding="utf-8")
        )
        source = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))

        self.assertIn("hooks", variant)
        self.assertTrue(variant["hooks"], "the named file declares no events")
        self.assertLess(
            set(variant["hooks"]),
            set(source["hooks"]),
            "the variant's events are not a strict subset of the source's",
        )


class TestADivergentEmitterIsCaught(_AssertNotNoneMixin, unittest.TestCase):
    """Mutate the emitter's declared name and the chain must break.

    The rows above compare what the manifest declares against what the hooks
    emitter wrote. This asks the sharper question: is that comparison actually
    wired to `manifest_emit`'s own literal, or would it keep passing if that
    literal changed? The mutation runs against a COPY of the emitter loaded under
    another module name — the shipped file is never written, which is the rule a
    mutation run in this sprint broke once by editing the real tree and shipping
    two stray lines.
    """

    def _mutant_emit(self, replacement: str):
        """A copy of the manifest emitter that declares *replacement* instead."""
        source = _PLUGIN_ROOT / "scripts" / "manifest_emit.py"
        text = source.read_text(encoding="utf-8")

        # Ask the emitter what it declares rather than writing that string here;
        # a literal would be a fourth copy of the very name under test.
        declared = manifest_emit.transform({})["hooks"]
        mutated = text.replace(declared, replacement)
        self.assertNotEqual(
            mutated,
            text,
            f"the mutation replaced nothing — {declared!r} is not a literal in "
            "the emitter any more, so this row would prove nothing",
        )

        target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)
        path = target / "manifest_emit_mutant.py"
        path.write_text(mutated, encoding="utf-8")

        spec = self._assert_not_none(
            importlib.util.spec_from_file_location("manifest_emit_mutant", path)
        )
        module = importlib.util.module_from_spec(spec)
        self._assert_not_none(spec.loader).exec_module(module)
        return module

    def test_an_emitter_declaring_another_name_fails_the_chain(self):
        root = _fixture_plugin_root(self)
        produced = hooks_emit.emit(
            source=root / "hooks" / "hooks.json", out_dir=root / "hooks"
        )
        mutant = self._mutant_emit("./hooks/hooks.mutant.json")
        derived = mutant.emit(
            source=root / ".claude-plugin" / "plugin.json",
            out_dir=root / ".codex-plugin",
        )

        self.assertNotEqual(
            _declared_hooks_path(derived, root),
            produced.resolve(),
            "a manifest emitter declaring a name the hooks emitter never writes "
            "still satisfied the chain — the comparison has no teeth",
        )

    def test_the_shipped_emitter_is_untouched_by_that_mutation(self):
        """The mutation wrote to a copy. This is what says so.

        Asserted by content, because the row above is the kind of run that
        already damaged the shipped tree once in this sprint.
        """
        source = _PLUGIN_ROOT / "scripts" / "manifest_emit.py"
        before = source.read_bytes()
        self._mutant_emit("./hooks/hooks.mutant.json")

        self.assertEqual(source.read_bytes(), before)
        self.assertIn(
            manifest_emit.transform({})["hooks"],
            source.read_text(encoding="utf-8"),
            "the shipped emitter no longer declares the name it reports",
        )


if __name__ == "__main__":
    unittest.main()
