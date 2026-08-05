#!/usr/bin/env python3
"""The close preloads' abandonment detector, driven as a subprocess.

The other two detectors run in-process (`test_close_cycle_abandonment`); this
one is a preload script, so its pins have to run the real shell and read what
it left in the SMM. Split from that suite when the pair crossed the file cap —
the seam is the runner, not the story, and both halves share
`_abandonment_fixtures`.

Two directions, and the story needs both. Arming over an AGED survivor must
read it out before the arm overwrites it; arming over a YOUNG one must stay
silent, because the preload arms at skill LOAD — before the close's own first
gate can refuse — so every refused attempt leaves a survivor that the retry,
seconds later, would otherwise report as an abandoned cycle.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import close_cycle_abandonment
import markers
from _abandonment_fixtures import ARMING_MODES, _AbandonmentAssertions, arm_abandoned
from conftest import _PLUGIN_ROOT, _IntegrationTestCase


class TestClosePreloadRecordsBeforeArming(_AbandonmentAssertions, _IntegrationTestCase):
    """Arming over an AGED survivor reads it out first.

    The arm below overwrites the marker, so a silent overwrite would make the
    survivor vanish before any sweep could ever see it — eating the evidence
    the sweep exists to produce.

    Both halves are asserted deliberately. A silent overwrite still arms the
    new marker, so the marker-side assertion alone passes against exactly the
    implementation this story rejects; the recorded concern is the half that
    fails.
    """

    def _preload(self, mode: str) -> Path:
        return _PLUGIN_ROOT / "skills" / f"xp-{mode}-close" / "scripts" / "preload.sh"

    def _assert_records_before_arming(self, mode: str) -> None:
        arm_abandoned(self.smm_dir, "survivor")

        result = self._run_preload(self._preload(mode))
        self.assertEqual(result.returncode, 0, result.stderr)

        # Marker first, concern second — deliberately. A silent consume
        # satisfies this half, so reading the failure top-down shows exactly
        # which half a regression broke.
        armed = markers.marker_read(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE)
        self.assertNotEqual(
            armed,
            "survivor",
            "the armed marker must be THIS close's, not the survivor",
        )
        # And it must NAME this close's session, not merely differ from the
        # survivor's payload: that id is the only thing a detector in another
        # window can use to tell a running close from an abandoned one, so an
        # empty payload here silently drops the whole discriminator back to the
        # duration that could not decide it.
        self.assertTrue(
            armed, "arming must stamp the owning session, not an empty payload"
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

    def test_the_record_lands_before_this_close_s_counting_window(self):
        """The record is about the PREVIOUS cycle, so it must not count as one
        of THIS close's findings.

        Step 6's abort-default counts `severity=high` concerns raised after
        `CLOSE_START_TS`, and the auto-merge gate refuses on the same number.
        Recorded inside that window, a restart's own abandonment concern
        recommends aborting every restarted close — for a concern whose stated
        recovery IS the restart in progress. The log keeps it either way; only
        the window changes.
        """
        for mode in ARMING_MODES:
            with self.subTest(mode=mode):
                (self.smm_dir / "events.jsonl").write_text("")
                arm_abandoned(self.smm_dir, "survivor")

                result = self._run_preload(self._preload(mode))
                self.assertEqual(result.returncode, 0, result.stderr)

                recorded = datetime.fromisoformat(self._one_bypass_concern()["ts"])
                window_start = datetime.fromisoformat(
                    self._emitted_var(result.stdout, "CLOSE_START_TS")
                )
                self.assertLess(
                    recorded,
                    window_start,
                    "recorded inside this close's window, so Step 6 counts it "
                    "and defaults the restarted close to abort",
                )

    @staticmethod
    def _emitted_var(stdout: str, name: str) -> str:
        prefix = f"{name}="
        for line in stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
        raise AssertionError(f"preload emitted no {name}")

    def test_a_first_close_records_nothing(self):
        """No survivor is the normal case — arming must stay silent."""
        for mode in ARMING_MODES:
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

    def test_a_same_session_retry_records_nothing(self):
        """The preload arms at skill LOAD, before Step 0's verify gate and
        Step 1's pre-flight can refuse — so a red-acceptance refusal leaves a
        marker behind having run nothing, and the retry finds it. Every refused
        attempt would otherwise add a high-severity concern claiming a reviewer
        never ran, for a cycle that never passed its first gate.
        """
        for mode in ARMING_MODES:
            with self.subTest(mode=mode):
                (self.smm_dir / "events.jsonl").write_text("")
                markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "")

                result = self._run_preload(self._preload(mode))

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self._bypass_concerns(), [])


if __name__ == "__main__":
    unittest.main()
