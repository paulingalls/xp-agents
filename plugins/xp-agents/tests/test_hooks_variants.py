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
from typing import ClassVar

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


class TestUnrecognisedEventsDropped(unittest.TestCase):
    """The variant registers only events the second harness recognises.

    Both sets are spelled out HERE rather than imported from `hooks_emit`. A pin
    that reads the emitter's own table would assert only that the emitter agrees
    with itself; spelled literally, editing the table fails this pin and the
    edit has to be argued for.

    Provenance of the split: measured in the dual-target spike, one run, one
    harness version. Six registered events never fired and are recorded as
    unrecognised; unknown names are ignored SILENTLY there, so nothing in the
    host would report the mistake if this list were wrong. That is exactly why
    it is pinned rather than left implicit — see assumption 1b57219c9598, which
    records that a harness later recognising one of these keeps being stripped.
    """

    RECOGNISED: ClassVar[set[str]] = {
        "PreToolUse",
        "PostToolUse",
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "SubagentStart",
        "SubagentStop",
        "Stop",
    }
    UNRECOGNISED: ClassVar[set[str]] = {
        "PreCompact",
        "PostCompact",
        "PostToolUseFailure",
        "TeammateIdle",
        "TaskCompleted",
        "WorktreeCreate",
    }

    def setUp(self):
        self.source = json.loads(_SOURCE.read_text(encoding="utf-8"))["hooks"]
        self.codex = json.loads(_CODEX.read_text(encoding="utf-8"))["hooks"]

    def test_variant_registers_only_recognised_events(self):
        self.assertEqual(set(self.codex), self.RECOGNISED)

    def test_every_recognised_source_event_survives(self):
        """Guards the opposite failure: dropping too much, not too little."""
        expected = set(self.source) & self.RECOGNISED
        self.assertEqual(set(self.codex), expected)

    def test_dropped_events_are_exactly_the_unrecognised_ones(self):
        self.assertEqual(set(self.source) - set(self.codex), self.UNRECOGNISED)

    def test_surviving_entries_differ_only_by_the_declared_key_drops(self):
        """Dropping events and the two declared keys is the ONLY editing done.

        Without this, a transform that also rewrote a matcher, reordered
        entries or edited a command would still satisfy the three set
        assertions above.

        This began as a stricter claim — surviving entries byte-identical to
        the source — which was correct when event-dropping was the only rule.
        The timeout and async strips falsified it, and it failed loudly rather
        than letting the new edits through, which is the pin working. Restated
        against the current rule set: strip the SAME declared keys from the
        source and the two must then match exactly. The guard is intact, since
        a rewritten matcher or a reordered list still fails.
        """
        for event, entries in self.codex.items():
            expected = json.loads(json.dumps(self.source[event]))
            for entry in expected:
                for hook in entry.get("hooks", []):
                    hook.pop("timeout", None)
                    hook.pop("async", None)
            self.assertEqual(entries, expected, f"{event} entry rewritten")


def _all_hook_objects(manifest: dict) -> list[tuple[str, dict]]:
    """Every (event, hook-object) pair in a manifest, flattened."""
    return [
        (event, hook)
        for event, entries in manifest["hooks"].items()
        for entry in entries
        for hook in entry.get("hooks", [])
    ]


class TestNoTimeoutInTheVariant(unittest.TestCase):
    """The variant ships no `timeout` value at all.

    NOT because absence is safe. Removing the key selects the harness's
    DEFAULT, and that default is equally unmeasured — this is a choice between
    two unknowns, not the removal of a risk. What was measured is only that a
    SessionEnd timeout drew a clamp warning, and two readings fit it: the
    harness caps SessionEnd at 3s regardless, or it reads the number as
    SECONDS, in which case every timeout in a manifest is off by 1000x. Those
    were the only two timeout values exercised, so nothing distinguishes them.

    Shipping a number would encode a guess about which reading is right. The
    milestone constraint therefore says ship none until one run tells them
    apart. Harmless today because nothing executes on that harness yet — the
    honesty matters when it does.
    """

    def setUp(self):
        self.source = json.loads(_SOURCE.read_text(encoding="utf-8"))
        self.codex = json.loads(_CODEX.read_text(encoding="utf-8"))

    def test_source_still_carries_timeouts(self):
        """Non-vacuity guard for the pin below.

        If the source ever stops declaring timeouts, the strip assertion
        becomes trivially true and would keep passing while the emitter's rule
        was deleted. This fails first and says why.
        """
        with_timeout = [
            f"{event}:{hook.get('command', '?')}"
            for event, hook in _all_hook_objects(self.source)
            if "timeout" in hook
        ]
        self.assertTrue(
            with_timeout,
            "hooks.json declares no timeout anywhere, so the strip pin below "
            "proves nothing — re-point it or delete both.",
        )

    def test_variant_declares_no_timeout(self):
        offenders = [
            f"{event}:{hook.get('command', '?')} timeout={hook['timeout']}"
            for event, hook in _all_hook_objects(self.codex)
            if "timeout" in hook
        ]
        self.assertEqual(offenders, [], "; ".join(offenders))


class TestNoAsyncInTheVariant(unittest.TestCase):
    """The variant ships no `async` flag.

    Measured, and it corrects the plan doc: `async: true` on SessionEnd is NOT
    skipped there — the harness announces "running async SessionEnd hook
    synchronously" and the handler's side effect landed in the same run. So the
    flag is a no-op that buys nothing and emits a warning per fire. Stripping
    it is tidying, and unlike the timeout rule it forfeits nothing, because the
    behaviour it requests is not available either way.
    """

    def setUp(self):
        self.source = json.loads(_SOURCE.read_text(encoding="utf-8"))
        self.codex = json.loads(_CODEX.read_text(encoding="utf-8"))

    def test_source_still_carries_async(self):
        """Non-vacuity guard, same argument as the timeout pin's."""
        with_async = [
            event for event, hook in _all_hook_objects(self.source) if "async" in hook
        ]
        self.assertTrue(with_async, "hooks.json declares no async — pin proves nothing")

    def test_variant_declares_no_async(self):
        offenders = [
            f"{event}:{hook.get('command', '?')}"
            for event, hook in _all_hook_objects(self.codex)
            if "async" in hook
        ]
        self.assertEqual(offenders, [], "; ".join(offenders))


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
        import hooks_emit

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "hooks.json"
            original = _SOURCE.read_bytes()
            source.write_bytes(original)

            hooks_emit.emit(source=source, out_dir=work)

            self.assertEqual(source.read_bytes(), original, "emitter wrote its source")

    def test_emitting_creates_only_the_variant(self):
        import hooks_emit

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            hooks_emit.emit(source=_SOURCE, out_dir=work)
            self.assertEqual(
                sorted(p.name for p in work.iterdir()),
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


if __name__ == "__main__":
    unittest.main()
