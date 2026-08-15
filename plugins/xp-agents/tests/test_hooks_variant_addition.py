#!/usr/bin/env python3
"""Pins for the ADDITION half of the hooks-variant derivation.

`scripts/hooks_emit.py` derives `hooks/hooks.codex.json` from `hooks/hooks.json`
mostly by subtraction (`test_hooks_variant_subtraction.py`). This file owns the
one rule that runs the other way: hook objects the VARIANT carries and the
source does not.

Why the rule has to exist at all: the two harnesses trigger on different
events. Harness 1 sees a skill invocation as a tool call; harness 2 has no skill
tool call, and the skill's body reaches the model through a shell read instead.
An entry present only in the derived file cannot be expressed by subtracting
from a source that must not contain it.

Why a hook object appended to an existing entry, rather than a second entry
sharing a matcher: counted across both shipped manifests, one entry carrying
many hook objects occurs six times (`Stop` carries six, `UserPromptSubmit`
three), while two entries sharing a matcher on one event has never shipped. The
merge rules of the second harness are recorded as undocumented, so the addition
takes the shape that harness already runs rather than the shape nothing has
exercised. Every pin in this file asserts JSON shape, so an entry that never
FIRED would pass here and surface only much later.

The declared additions are spelled literally below and imported from nowhere.
A pin that reads `hooks_emit`'s own table asserts only that the emitter agrees
with itself — the same argument that keeps the recognised-event sets spelled out
in the subtraction suite.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import hooks_emit
from _hooks_variant_fixtures import _CODEX, _SOURCE, _all_hook_objects

# The expectation, recorded — never derived from the emitter. Keyed by the
# (event, matcher) pair whose entry each hook object is appended to.
ADDITIONS: dict[tuple[str, str], list[dict]] = {
    ("PreToolUse", "Bash"): [
        {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/preload_injection.py",
        }
    ],
}


def _triples(
    manifest: dict, events: set[str] | None = None
) -> set[tuple[str, str, str]]:
    """Every (event, matcher, command) in a manifest, optionally restricted.

    Matcher is normalised to `""` when absent, so an event whose entry carries
    no matcher compares as itself rather than as `None`.
    """
    out = set()
    for event, entries in manifest["hooks"].items():
        if events is not None and event not in events:
            continue
        for entry in entries:
            matcher = entry.get("matcher") or ""
            for hook in entry.get("hooks", []):
                out.add((event, matcher, hook["command"]))
    return out


def _declared_triples() -> set[tuple[str, str, str]]:
    return {
        (event, matcher, hook["command"])
        for (event, matcher), hooks in ADDITIONS.items()
        for hook in hooks
    }


def _missing_additions(manifest: dict) -> list[str]:
    """Declared additions absent from `manifest`, each described by name.

    Factored out so the mutation proof below can run the SAME check against a
    manifest regenerated from an emptied declaration. Asserting the shipped pin
    is red under mutation is otherwise impossible: the pin reads the checked-in
    variant, which emptying the emitter's table does not touch until something
    regenerates.
    """
    present = _triples(manifest)
    return [
        f"{event}:{matcher} is missing the variant-only hook {command!r}"
        for event, matcher, command in sorted(_declared_triples())
        if (event, matcher, command) not in present
    ]


class TestDeclaredAdditionsReachTheVariant(unittest.TestCase):
    """Each declared hook object lands on its declared entry, and nowhere else.

    AC1, both halves: it appears in the derived variant, and it does not appear
    in the source manifest.
    """

    def setUp(self):
        self.source = json.loads(_SOURCE.read_text(encoding="utf-8"))
        self.codex = json.loads(_CODEX.read_text(encoding="utf-8"))

    def test_the_declaration_is_not_empty(self):
        """Non-vacuity guard. Every assertion below iterates the declaration,
        so an emptied table would satisfy all of them by iterating nothing —
        the failure mode a recorded count exists to catch."""
        self.assertTrue(
            ADDITIONS, "no declared additions — the pins below scan nothing"
        )

    def test_every_declared_addition_reaches_the_variant(self):
        missing = _missing_additions(self.codex)
        self.assertEqual(missing, [], "; ".join(missing))

    def test_declared_additions_land_on_an_entry_that_already_exists(self):
        """The addition extends an entry rather than creating a second one
        sharing its matcher — the shape argument in this module's docstring.
        Asserted on the artifact, so an emitter that appended a new entry
        instead fails here rather than at story-011."""
        for event, matcher in sorted(ADDITIONS):
            with self.subTest(event=event, matcher=matcher):
                entries = [
                    entry
                    for entry in self.codex["hooks"].get(event, [])
                    if (entry.get("matcher") or "") == matcher
                ]
                self.assertEqual(
                    len(entries),
                    1,
                    f"{event}:{matcher} resolves to {len(entries)} entries in the "
                    "variant; the addition must extend the single existing entry, "
                    "not add a second one sharing its matcher",
                )

    def test_no_declared_addition_appears_in_the_source(self):
        """The other half of AC1. Also the property that keeps harness 1's
        manifest byte-identical: the addition exists only downstream."""
        leaked = sorted(_declared_triples() & _triples(self.source))
        self.assertEqual(
            leaked, [], f"variant-only hooks leaked into hooks.json: {leaked}"
        )


class TestVariantInventsNothing(unittest.TestCase):
    """Every command in the variant comes from the source or the declaration.

    Was `TestVariantIsDerivedBySubtraction`, whose name the addition rule
    falsified. Its original argument was that a subset claim INHERITS
    path-existence from the source's own pin
    (`tests/hooks/test_plugin_integrity_structure_and_close.py`, which reads
    `hooks.json` only). The addition breaks exactly that inheritance: a declared
    command is not in the source, so nothing proves its script exists. That gap
    is recorded as debt for story-011, which creates the script this
    declaration names — until then the variant ships a command with no file
    behind it, deliberately and on a branch that is never released.
    """

    def setUp(self):
        self.source = json.loads(_SOURCE.read_text(encoding="utf-8"))
        self.codex = json.loads(_CODEX.read_text(encoding="utf-8"))

    def _commands(self, manifest: dict) -> set[str]:
        return {hook["command"] for _, hook in _all_hook_objects(manifest)}

    def test_variant_commands_come_from_the_source_or_the_declaration(self):
        declared = {command for _, _, command in _declared_triples()}
        invented = self._commands(self.codex) - self._commands(self.source) - declared
        self.assertEqual(
            invented, set(), f"commands in neither source nor declaration: {invented}"
        )

    def test_the_variant_carries_nothing_beyond_source_plus_declaration(self):
        """The strong both-directions guard, stated over (event, matcher,
        command) rather than over commands alone: a command that legitimately
        appears somewhere in the source must still not be grafted onto a
        DIFFERENT event or matcher in the variant."""
        surviving = set(self.codex["hooks"])
        extra = _triples(self.codex) - _triples(self.source, events=surviving)
        self.assertEqual(
            extra,
            _declared_triples(),
            "the variant carries hook objects the source does not, beyond the "
            "declared additions",
        )


class TestSurvivingEntriesAreCarriedAcross(unittest.TestCase):
    """Dropping events, dropping the two declared keys, and appending the
    declared additions is the ONLY editing done.

    Restated from the subtraction suite, which is where it lived until the
    addition rule made its claim false: the variant now legitimately carries
    hook objects the source does not. Without this pin, a transform that also
    rewrote a matcher, reordered entries or edited a command would still
    satisfy every set assertion in this file.

    Stated as: strip the same declared keys from the source, append the
    declared additions to the same entries, and the two must match exactly —
    order included, so a reordered list still fails.
    """

    def setUp(self):
        self.source = json.loads(_SOURCE.read_text(encoding="utf-8"))["hooks"]
        self.codex = json.loads(_CODEX.read_text(encoding="utf-8"))["hooks"]

    def test_surviving_entries_differ_only_by_key_drops_and_declared_additions(self):
        for event, entries in self.codex.items():
            expected = json.loads(json.dumps(self.source[event]))
            for entry in expected:
                for hook in entry.get("hooks", []):
                    hook.pop("timeout", None)
                    hook.pop("async", None)
                added = ADDITIONS.get((event, entry.get("matcher") or ""))
                if added:
                    entry.setdefault("hooks", []).extend(json.loads(json.dumps(added)))
            self.assertEqual(entries, expected, f"{event} entry rewritten")


class TestThePinWouldCatchARemovedAddition(unittest.TestCase):
    """The pins above are proven non-vacuous by mutating the emitter, not by
    inspection.

    Both cases run permanently rather than being performed once and described:
    a mutation demonstrated in a session and written up in a docstring stops
    protecting anything the moment someone edits the code it described.

    Each asserts on the MESSAGE, never on the exception type alone.
    `assertRaises(AssertionError)` also catches an assertion this module raises
    for its own internal reasons, so a pin that had stopped resolving anything
    would satisfy it — the defect found in story-002's review.
    """

    def _emit_with(self, table: dict) -> dict:
        with (
            patch.object(hooks_emit, "_VARIANT_ONLY_HOOKS", table),
            tempfile.TemporaryDirectory() as tmp,
        ):
            out_dir = Path(tmp)
            hooks_emit.emit(source=_SOURCE, out_dir=out_dir)
            return json.loads(
                (out_dir / "hooks.codex.json").read_text(encoding="utf-8")
            )

    def test_emptying_the_declaration_makes_the_pin_name_the_lost_entry(self):
        """AC4. Regenerating from an empty table must fail the presence check,
        and the failure must name the entry — event, matcher and command — so a
        reader learns WHICH hook went missing rather than that a count moved."""
        produced = self._emit_with({})
        missing = _missing_additions(produced)

        self.assertTrue(missing, "emptying the declaration left the pin green")
        self.assertIn("PreToolUse:Bash", missing[0])
        self.assertIn("preload_injection.py", missing[0])

        # Reverted: the real table is in force again, proven rather than assumed.
        self.assertEqual(_missing_additions(self._emit_with(ADDITIONS)), [])

    def test_declaring_an_addition_for_no_existing_entry_raises(self):
        """The emitter's own guard against a reachable state: a source edit that
        renames or removes the target entry. Without the raise the addition
        becomes a no-op whose output still regenerates and still parses."""
        with self.assertRaisesRegex(ValueError, r"PreToolUse:NoSuchMatcher"):
            self._emit_with(
                {
                    ("PreToolUse", "NoSuchMatcher"): [
                        {"type": "command", "command": "python3 x.py"}
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
