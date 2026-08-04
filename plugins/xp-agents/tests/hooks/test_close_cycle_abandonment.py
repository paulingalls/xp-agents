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

Every pin for the story lives in this one file so the acceptance command
covers the whole proof.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import close_cycle_abandonment
import close_cycle_stop_gate
import markers
import session_markers
from conftest import (
    _PLUGIN_ROOT,
    _HookTestCase,
    _IntegrationTestCase,
    _make_stop_input,
    _MixinBase,
)
from event_schema import (
    CONCERN_KIND_CLOSE_CYCLE_BYPASS,
    CONTENT_BUDGETS,
    EVENT_TYPE_CONCERN,
)

_SHARED_PIPELINE = _PLUGIN_ROOT / "scripts" / "_close_pipeline_shared.md"
_ARMING_MODES = ("sprint", "plan", "free")


def _marker_payload(marker) -> str | dict:
    """A writable payload for any marker in the stale-session set."""
    return {} if marker.content_type == "json" else ""


class _AbandonmentAssertions(_MixinBase):
    """Shared reads over the recorded abandonment concerns.

    Both concrete bases below define `_read_events`, but `TestCase` (what
    `_MixinBase` resolves to for pyright) does not — so it is declared here
    under TYPE_CHECKING only, which adds nothing at runtime.
    """

    if TYPE_CHECKING:

        def _read_events(self) -> list[dict]: ...

    def _bypass_concerns(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("type") == EVENT_TYPE_CONCERN
            and (e.get("metadata") or {}).get("kind") == CONCERN_KIND_CLOSE_CYCLE_BYPASS
        ]

    def _one_bypass_concern(self) -> dict:
        found = self._bypass_concerns()
        self.assertEqual(len(found), 1, f"expected exactly one, got {found!r}")
        return found[0]


class TestSweepRecordsAbandonment(_AbandonmentAssertions, _HookTestCase):
    """The backstop detector: a marker that survived to the next fresh start."""

    def test_sweep_records_a_high_severity_concern_and_clears_the_marker(self):
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

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
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

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
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")
        session_markers.sweep_stale_session_markers(self.smm_dir)
        content = self._one_bypass_concern()["content"]
        self.events_file.write_text("")
        return content

    def _aged_stop_content(self) -> str:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")
        path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        aged = (
            path.stat().st_mtime
            - close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC
            - 60
        )
        os.utime(path, (aged, aged))
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
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")
        path = markers.marker_path(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        aged = (
            path.stat().st_mtime
            - close_cycle_stop_gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC
            - 60
        )
        os.utime(path, (aged, aged))

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

    def test_the_release_step_names_both_markers(self):
        text = _SHARED_PIPELINE.read_text(encoding="utf-8")
        start = text.index("### Step 6b")
        step = text[start:]
        for name in ("CLOSE_CYCLE_ID", "CLOSE_CYCLE_ACTIVE"):
            with self.subTest(marker=name):
                self.assertIn(
                    name,
                    step,
                    f"Step 6b must release {name} — an agent follows this step "
                    f"list, and a marker it never names is never released",
                )


class TestClosePreloadRecordsBeforeArming(_AbandonmentAssertions, _IntegrationTestCase):
    """Starting a close proves the previous one is over.

    This is the DOMINANT path, not an edge case: a close aborts at an early
    step, the operator retries in the same session, and a silent consume would
    make the survivor vanish before any sweep could ever see it — eating the
    evidence the sweep exists to produce.

    Both halves are asserted deliberately. A silent consume still arms the new
    marker, so the marker-side assertion alone passes against exactly the
    implementation this story rejects; the recorded concern is the half that
    fails.
    """

    def _preload(self, mode: str) -> Path:
        return _PLUGIN_ROOT / "skills" / f"xp-{mode}-close" / "scripts" / "preload.sh"

    def _assert_records_before_arming(self, mode: str) -> None:
        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "survivor")

        result = self._run_preload(self._preload(mode))
        self.assertEqual(result.returncode, 0, result.stderr)

        # Marker first, concern second — deliberately. A silent consume
        # satisfies this half, so reading the failure top-down shows exactly
        # which half a regression broke.
        self.assertEqual(
            markers.marker_read(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE),
            "",
            "the armed marker must be THIS close's, not the survivor",
        )
        concern = self._one_bypass_concern()
        self.assertEqual(concern["severity"], "high")
        self.assertEqual(
            concern["metadata"].get("detector"),
            close_cycle_abandonment.DETECTOR_CLOSE_RESTART,
        )

    def test_sprint_close_records_before_arming(self):
        self._assert_records_before_arming("sprint")

    def test_plan_close_records_before_arming(self):
        self._assert_records_before_arming("plan")

    def test_free_close_records_before_arming(self):
        self._assert_records_before_arming("free")

    def test_a_first_close_records_nothing(self):
        """No survivor is the normal case — arming must stay silent."""
        for mode in _ARMING_MODES:
            with self.subTest(mode=mode):
                # Each mode starts from a clean close: the previous iteration
                # armed the marker, and leaving it would make the NEXT mode a
                # survivor case — the opposite of what this test measures.
                (self.smm_dir / "events.jsonl").write_text("")
                markers.marker_consume(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
                result = self._run_preload(self._preload(mode))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self._bypass_concerns(), [])
                self.assertTrue(
                    markers.marker_exists(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
                )


if __name__ == "__main__":
    unittest.main()
