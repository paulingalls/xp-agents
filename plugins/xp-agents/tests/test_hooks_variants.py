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
import subprocess
import sys
import tempfile
import unittest
from fnmatch import fnmatch
from pathlib import Path
from typing import ClassVar

import tomllib

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import hooks_emit
from _paths import _PLUGIN_ROOT, _SCRIPTS_DIR

_HOOKS_DIR = _PLUGIN_ROOT / "hooks"
_SOURCE = _HOOKS_DIR / "hooks.json"
_CODEX = _HOOKS_DIR / "hooks.codex.json"
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

        Stated as: strip the SAME declared keys from the source and the two
        must match exactly. A rewritten matcher or a reordered list fails.
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

        Counted over SURVIVING events only: a timeout declared solely on an
        event the variant drops cannot reach the variant either way, so it
        would satisfy a source-wide count while leaving the strip rule unpinned.
        """
        with_timeout = [
            f"{event}:{hook.get('command', '?')}"
            for event, hook in _all_hook_objects(self.source)
            if "timeout" in hook and event in self.codex["hooks"]
        ]
        self.assertTrue(
            with_timeout,
            "no surviving event in hooks.json declares a timeout, so the strip "
            "pin below proves nothing — re-point it or delete both.",
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
        """Non-vacuity guard, same argument as the timeout pin's.

        Surviving events only, and for `async` that is not hypothetical: the
        source declares it on SessionEnd and on PostToolUseFailure, and the
        latter is dropped whole. A source-wide count would stay green on
        PostToolUseFailure alone while the strip rule went unpinned.
        """
        with_async = [
            event
            for event, hook in _all_hook_objects(self.source)
            if "async" in hook and event in self.codex["hooks"]
        ]
        self.assertTrue(
            with_async,
            "no surviving event in hooks.json declares async — pin proves nothing",
        )

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
    """

    def test_cli_emits_a_valid_manifest_into_a_target_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
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
