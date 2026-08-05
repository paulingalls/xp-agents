#!/usr/bin/env python3
"""A close cycle that dies must leave a record, not a silent marker.

The gate that blocks Stop mid-close was already correct about ALLOWING the
stop once the platform's re-entry flag is latched — that allow is loop
prevention and is pinned here as a regression, not treated as the defect.

What was missing is the record. The close-start marker is armed by the preload
and released by the reviewer's completion, so every exit before that reviewer
leaves it behind; the next fresh session then consumed it SILENTLY, and the one
component that positively knew a close cycle had died threw the fact away.
"the reviewer never ran" and "the reviewer ran and passed" were
indistinguishable from outside.

Three detectors can now be first to learn it, and all three route through one
owner (`scripts/close_cycle_abandonment.py`) so they cannot drift apart:

  - the aged-Stop bypass in `close_cycle_stop_gate`
  - the SessionStart sweep in `session_markers`
  - a new close arming over a survivor, in the three close preloads

They also share its AGE rule, and that half is load-bearing in the opposite
direction. The marker is not session-scoped and the SMM is shared across
windows and worktrees, so two of the three routinely see a cycle that is still
RUNNING: a second window's fresh start, and a close whose own first gate
refused and is being retried. Recording either files a high-severity concern
that the live close's own Step 6 count reads as a reason to abort — a close
that never failed, told to abort by its neighbour.

The three detectors' pins live in this file and its `_preload` sibling — one
per runner, in-process and subprocess. The acceptance command covers both.
"""

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import close_cycle_abandonment
import close_cycle_stop_gate
import markers
import session_markers
from _abandonment_fixtures import _AbandonmentAssertions, arm_abandoned
from conftest import _PLUGIN_ROOT, _HookTestCase, _make_stop_input
from event_schema import CONTENT_BUDGETS, EVENT_TYPE_CONCERN

_SHARED_PIPELINE = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"


def _marker_payload(marker) -> str | dict:
    """A writable payload for any marker in the stale-session set."""
    return {} if marker.content_type == "json" else ""


class TestSweepRecordsAbandonment(_AbandonmentAssertions, _HookTestCase):
    """The backstop detector: a marker that survived to the next fresh start."""

    def test_sweep_records_a_high_severity_concern_and_clears_the_marker(self):
        arm_abandoned(self.smm_dir)

        session_markers.sweep_stale_session_markers(self.smm_dir)

        concern = self._one_bypass_concern()
        self.assertEqual(concern["severity"], "high")
        # Names what was outstanding, and how to recover it.
        self.assertIn("xp-close-reviewer", concern["content"])
        self.assertIn("Recovery:", concern["content"])
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "the sweep must still clear the marker it records",
        )

    def test_the_record_names_which_detector_fired(self):
        """Three detectors share one content, so the log reader can only tell
        them apart by metadata."""
        arm_abandoned(self.smm_dir)

        session_markers.sweep_stale_session_markers(self.smm_dir)

        metadata = self._one_bypass_concern()["metadata"]
        self.assertEqual(
            metadata.get("detector"), close_cycle_abandonment.DETECTOR_SESSION_SWEEP
        )


class TestSweepStaysSilentOtherwise(_AbandonmentAssertions, _HookTestCase):
    """The half that stops the signal becoming a per-session tax.

    The sweep runs at EVERY fresh session start. Recording unconditionally
    would file a high-severity concern on a clean session, which is worse than
    the silence this story removed: an operator who sees it every morning stops
    reading it, and the real abandonment goes with it.
    """

    def test_no_marker_records_nothing(self):
        session_markers.sweep_stale_session_markers(self.smm_dir)

        self.assertEqual(self._read_events(), [])

    def test_the_other_stale_markers_record_nothing(self):
        """The other five leak for ordinary reasons and must stay silent."""
        others = [
            m
            for m in session_markers._STALE_SESSION_MARKERS
            if m is not markers.CLOSE_CYCLE_ACTIVE
        ]
        self.assertTrue(others, "non-vacuity: the stale set has other members")
        for marker in others:
            markers.marker_write(self.smm_dir, marker, _marker_payload(marker))

        session_markers.sweep_stale_session_markers(self.smm_dir)

        self.assertEqual(self._read_events(), [])
        for marker in others:
            with self.subTest(marker=marker.name):
                self.assertFalse(
                    markers.marker_exists(self.smm_dir, marker),
                    "the sweep must still consume every marker in the set",
                )


class TestSweepLeavesALiveCycleAlone(_AbandonmentAssertions, _HookTestCase):
    """The marker is not session-scoped and the SMM is shared across windows.

    Window A is mid-close, marker armed. The user opens a second window, or
    runs `/clear` — SessionStart, fresh start, sweep. That sweep is looking at
    window A's LIVE cycle, and it has nothing that says so beyond the marker's
    age.

    Recording there is worse than the silence the story removed: the concern is
    untagged and carries no `files`, so window A's Step 6 count excludes it by
    neither `--cycle-id` nor `--diff-paths` nor `--since-ts`. Its merge prompt
    flips to Abort and its auto-merge gate refuses, for a close that never
    failed. Consuming there also silently disarms window A's Stop gate.
    """

    def test_a_young_marker_records_nothing(self):
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

        session_markers.sweep_stale_session_markers(self.smm_dir)

        self.assertEqual(self._bypass_concerns(), [])

    def test_a_young_marker_survives_the_sweep(self):
        """The other half. A silent consume records nothing either, and would
        pass the assertion above while still disarming the live close."""
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

        session_markers.sweep_stale_session_markers(self.smm_dir)

        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "the sweep consumed a live close's gate marker",
        )

    def test_the_marker_is_not_in_the_unconditional_stale_set(self):
        """Structural, not behavioural: membership there IS an unconditional
        consume, whatever the recorder decides first."""
        self.assertNotIn(
            markers.CLOSE_CYCLE_ACTIVE, session_markers._STALE_SESSION_MARKERS
        )


class TestARetriedCloseIsNotAnAbandonedOne(_AbandonmentAssertions, _HookTestCase):
    """The preloads arm the marker at skill LOAD, before Step 0's verify gate
    and Step 1's pre-flight can refuse.

    So a red-acceptance refusal leaves a marker behind having run nothing at
    all, and the retry after fixing the tests finds it. Recording there claims
    a reviewer "was expected to run but never did" for a cycle that never
    passed its first gate — once per refused attempt.
    """

    def test_a_young_survivor_records_nothing(self):
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

        recorded = close_cycle_abandonment.record_abandonment(
            self.smm_dir, close_cycle_abandonment.DETECTOR_CLOSE_RESTART
        )

        self.assertFalse(recorded)
        self.assertEqual(self._bypass_concerns(), [])

    def test_an_aged_survivor_still_records(self):
        """Non-vacuity: the age rule must not have switched the detector off."""
        arm_abandoned(self.smm_dir)

        recorded = close_cycle_abandonment.record_abandonment(
            self.smm_dir, close_cycle_abandonment.DETECTOR_CLOSE_RESTART
        )

        self.assertTrue(recorded)
        self.assertEqual(len(self._bypass_concerns()), 1)


class TestADroppedAppendKeepsTheMarker(_AbandonmentAssertions, _HookTestCase):
    """Consuming after a dropped append destroys the evidence AND the record of
    it: no later detector can re-find a marker that is gone.

    The lock has a 10s timeout and no unlocked fallback, so a drop is a real
    outcome under concurrent appends — the one this module exists to prevent.
    """

    def test_a_failed_append_records_nothing_and_keeps_the_marker(self):
        import _append_impl

        arm_abandoned(self.smm_dir)
        original = _append_impl.append_event

        def _boom(*_args, **_kwargs):
            raise _append_impl.LockTimeoutError("events.lock busy")

        _append_impl.append_event = _boom
        try:
            recorded = close_cycle_abandonment.record_abandonment(
                self.smm_dir, close_cycle_abandonment.DETECTOR_SESSION_SWEEP
            )
        finally:
            _append_impl.append_event = original

        self.assertFalse(recorded, "returned True for a record that never landed")
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "the marker is the only thing a later detector can re-find",
        )


class TestTheAgedStopBypassClaimsOnlyWhatItRecorded(_HookTestCase):
    """The stderr line says "high-severity concern recorded". An operator who
    cannot find that concern cannot tell a dropped append from one that was
    never attempted, so the line is written only when one landed."""

    def _run_bypass(self) -> str:
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            close_cycle_stop_gate.run(
                _make_stop_input(stop_hook_active=True), smm_dir=self.smm_dir
            )
        return buffer.getvalue()

    def test_a_young_marker_writes_no_claim(self):
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

        self.assertEqual(self._run_bypass(), "")

    def test_an_aged_marker_writes_the_claim(self):
        arm_abandoned(self.smm_dir)

        self.assertIn("concern recorded", self._run_bypass())


class TestOneContentOneBudgetOwner(_AbandonmentAssertions, _HookTestCase):
    """Both detectors emit the SAME content from the shared owner.

    Two hand-rolled constructions would drift, and only one of them would be
    budget-pinned — an over-budget concern is dropped by `append_safe`, which
    is a real prior outage on this exact gate.
    """

    def test_the_content_fits_the_concern_budget(self):
        budget = self._assert_not_none(
            CONTENT_BUDGETS[EVENT_TYPE_CONCERN],
            "concern budget must remain enforced",
        )
        self.assertLessEqual(
            len(close_cycle_abandonment.CONCERN_CONTENT),
            budget,
            "over budget, so append_safe drops the concern and abandonment "
            "never surfaces — the failure this pin exists for",
        )

    def test_the_recovery_hint_names_only_the_closes_that_arm_the_gate(self):
        """Story-close deliberately does not arm this marker; naming it in the
        recovery hint would send an operator to re-run the wrong close."""
        recovery = close_cycle_abandonment.RECOVERY
        self.assertIn("{sprint,plan,free}", recovery)
        self.assertNotIn("story", recovery)

    def test_both_detectors_emit_the_shared_content(self):
        sweep_content = self._sweep_content()
        aged_stop_content = self._aged_stop_content()

        self.assertEqual(sweep_content, aged_stop_content)
        self.assertEqual(sweep_content, close_cycle_abandonment.CONCERN_CONTENT)

    def _sweep_content(self) -> str:
        arm_abandoned(self.smm_dir)
        session_markers.sweep_stale_session_markers(self.smm_dir)
        content = self._one_bypass_concern()["content"]
        self.events_file.write_text("")
        return content

    def _aged_stop_content(self) -> str:
        arm_abandoned(self.smm_dir)
        with redirect_stderr(io.StringIO()):
            close_cycle_stop_gate.run(
                _make_stop_input(stop_hook_active=True), smm_dir=self.smm_dir
            )
        concern = self._one_bypass_concern()
        self.assertEqual(
            concern["metadata"].get("detector"),
            close_cycle_abandonment.DETECTOR_AGED_STOP,
            "the aged-Stop detector must tag itself, not the sweep",
        )
        return concern["content"]


class TestBypassStaysAllowed(_HookTestCase):
    """The decision this story did NOT reverse.

    With the platform's Stop re-entry flag latched the gate allows the stop —
    exactly as its three sibling Stop gates do, and for the same reason:
    infinite-loop prevention. Recording the abandonment is what makes that
    allow honest; blocking instead would reintroduce the loop those guards
    exist to prevent.
    """

    def test_a_young_marker_still_allows_the_stop(self):
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

        result = close_cycle_stop_gate.run(
            _make_stop_input(stop_hook_active=True), smm_dir=self.smm_dir
        )

        self.assertIsNone(result)

    def test_an_aged_marker_still_allows_the_stop(self):
        arm_abandoned(self.smm_dir)

        with redirect_stderr(io.StringIO()):
            result = close_cycle_stop_gate.run(
                _make_stop_input(stop_hook_active=True), smm_dir=self.smm_dir
            )

        self.assertIsNone(result, "recording an abandonment must not start blocking")


class TestStep6bReleasesBothMarkers(unittest.TestCase):
    """Step 6b runs on every exit, including abort.

    Neither the sweep nor the record-before-arm covers "abort, no retry, keep
    working in the same session": the marker stays set and the gate blocks
    every Stop that has no re-entry flag latched. That is the literal symptom
    recorded from a live close and cleared by hand.
    """

    def _step_6b(self) -> str:
        text = _SHARED_PIPELINE.read_text(encoding="utf-8")
        return text[text.index("### Step 6b") :]

    def test_the_release_step_names_both_markers(self):
        step = self._step_6b()
        for name in ("CLOSE_CYCLE_ID", "CLOSE_CYCLE_ACTIVE"):
            with self.subTest(marker=name):
                self.assertIn(
                    name,
                    step,
                    f"Step 6b must release {name} — an agent follows this step "
                    f"list, and a marker it never names is never released",
                )

    def test_the_gate_release_is_scoped_to_the_modes_that_arm_it(self):
        """This file is read by all FOUR closes, and story-close arms no gate.

        An unscoped consume there clears an enclosing close's LIVE marker: a
        lead mid-/xp-free-close who pauses to run /xp-accept (which drives
        /xp-story-close) comes back with the gate off and the marker gone, so
        none of the three detectors can ever report it — the branch is left
        unmerged with nothing in the log.
        """
        step = self._step_6b()
        gate_line = next(
            line for line in step.splitlines() if "CLOSE_CYCLE_ACTIVE" in line
        )
        self.assertIn(
            "sprint/plan/free-close",
            gate_line,
            "the gate release must name whose it is; story-close reads this "
            "same file and arms no gate",
        )
        self.assertIn("Story-close arms none", step)


if __name__ == "__main__":
    unittest.main()
