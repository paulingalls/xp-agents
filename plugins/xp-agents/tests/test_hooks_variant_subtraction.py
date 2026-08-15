#!/usr/bin/env python3
"""Pins for the SUBTRACTION half of the hooks-variant derivation.

`scripts/hooks_emit.py` derives `hooks/hooks.codex.json` from `hooks/hooks.json`
by dropping events the second harness does not recognise, every `timeout`, and
every `async` — and never writes the source. This file owns those three rules.

Split out of `test_hooks_variants.py`, which now keeps the pins that assert
properties of the ARTIFACT (it regenerates clean, it parses, the emitter does
not touch its input) while the derivation RULES live here and in
`test_hooks_variant_addition.py`. The split was forced: the original file stood
at 445 lines against a 500-line cap with the addition rule still to land.

Every expectation below is spelled literally rather than imported from
`hooks_emit`. A pin that reads the emitter's own table asserts only that the
emitter agrees with itself.
"""

import json
import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from _hooks_variant_fixtures import _CODEX, _SOURCE, _all_hook_objects


class TestUnrecognisedEventsDropped(unittest.TestCase):
    """The variant registers only events the second harness recognises.

    Both sets are spelled out HERE rather than imported from `hooks_emit`. A pin
    that reads the emitter's own table would assert only that the emitter agrees
    with itself; spelled literally, editing the table fails this pin and the
    edit has to be argued for.

    Provenance of the split: measured in the dual-target spike, one run, one
    harness version. Four registered events are recorded as unrecognised;
    unknown names are ignored SILENTLY there, so nothing in the host would
    report the mistake if this list were wrong — see assumption 1b57219c9598,
    which records that a harness later recognising one keeps being stripped.

    The compaction pair sits in RECOGNISED on purpose. Neither fired in the
    spike — no run compacted — but the host emitted its own warning NAMING
    them, which is proof it knows the names. Reading "never fired" as
    "unrecognised" there dropped the event-log backup and the compaction pass
    from every session that compacts, filed as a limit nobody measured.
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
        "PreCompact",
        "PostCompact",
    }
    UNRECOGNISED: ClassVar[set[str]] = {
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

        Restated and relocated to `test_hooks_variant_addition.py` when the
        addition rule lands: from that point the variant legitimately carries
        hook objects the source does not, and this comparison has to account
        for them.
        """
        for event, entries in self.codex.items():
            expected = json.loads(json.dumps(self.source[event]))
            for entry in expected:
                for hook in entry.get("hooks", []):
                    hook.pop("timeout", None)
                    hook.pop("async", None)
            self.assertEqual(entries, expected, f"{event} entry rewritten")


class TestNoTimeoutInTheVariant(unittest.TestCase):
    """The variant ships no `timeout` value at all.

    Not because absence is safe — removing the key selects the harness's
    default. Because the UNIT differs, measured on an installed copy:
    `timeout: 2000` let a 3s handler run to completion (milliseconds would have
    killed it at 2s) and `timeout: 1` killed the same handler mid-run. Seconds,
    and enforced. The source declares MILLISECONDS, so carrying a value across
    literally asks for 2500 seconds where 2.5 was meant. That also retires the
    older reading of the SessionEnd clamp warning: it fired on 2500 and 1500
    because both are seconds meeting that event's 3s cap.

    Restoring a bound is therefore a conversion — with sub-second bounds
    unrepresentable as integers — which a later milestone owns, not a value to
    copy back into this transform.

    This pin also covers every hook object the ADDITION rule contributes: it
    scans the whole variant, so a declared addition carrying a timeout fails
    here. That is why the addition rule does not strip keys of its own.
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


if __name__ == "__main__":
    unittest.main()
