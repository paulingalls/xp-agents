#!/usr/bin/env python3
"""close_cycle_stop_gate threshold-split pin (sprint-104 story-005 Fix B).

The single `_CLOSE_CYCLE_AGE_THRESHOLD_SEC = 1800` constant served two
distinct timescales:

  1. Defer window — block the close-reviewer nudge while /code-review
     Step 4b is in flight. Must EXCEED the workflow's runtime (~10-15
     min /code-review high + headroom for /xp-quality-review consume
     + /security-review + AskUserQuestion sessions).

  2. Abandonment timeout — record an abandonment concern when the
     marker is truly stale. Must be SUBSTANTIALLY LONGER than the
     defer window so a legitimately long-running close (security
     review prompts, slow agent turns) doesn't trip a false-positive
     abandonment.

Sharing one value forces a compromise that fails both: too long for
defer (delays surfacing real abandonment) or too short for abandonment
(false positives during long workflows). This pin enforces the split.

Resolves the threshold-split cleanup item adopted 4 sessions
consecutive.
"""

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import close_cycle_stop_gate as gate


class TestCloseCycleThresholdSplit(unittest.TestCase):
    """Pin the split into defer_window + abandonment_timeout."""

    def test_defer_window_constant_exists(self):
        """Module exposes a defer-window constant."""
        self.assertTrue(
            hasattr(gate, "_CLOSE_CYCLE_DEFER_WINDOW_SEC"),
            "close_cycle_stop_gate must define _CLOSE_CYCLE_DEFER_WINDOW_SEC",
        )
        self.assertIsInstance(gate._CLOSE_CYCLE_DEFER_WINDOW_SEC, int)
        # Must EXCEED /code-review high observed runtime (~10-15 min)
        # plus quality-review + security-review headroom — at least 1200s.
        self.assertGreaterEqual(
            gate._CLOSE_CYCLE_DEFER_WINDOW_SEC,
            1200,
            "defer window must exceed observed /code-review high runtime",
        )

    def test_abandonment_timeout_constant_exists(self):
        """Module exposes an abandonment-timeout constant."""
        self.assertTrue(
            hasattr(gate, "_CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC"),
            "close_cycle_stop_gate must define _CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC",
        )
        self.assertIsInstance(gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC, int)

    def test_defer_window_and_abandonment_timeout_are_distinct(self):
        """The two timescales must be DIFFERENT values — that's the whole point.

        Abandonment must be substantially longer than defer so a slow
        legitimate workflow doesn't trip a false-positive abandonment.
        """
        self.assertNotEqual(
            gate._CLOSE_CYCLE_DEFER_WINDOW_SEC,
            gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC,
            "defer_window and abandonment_timeout must be distinct values",
        )
        self.assertGreater(
            gate._CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC,
            gate._CLOSE_CYCLE_DEFER_WINDOW_SEC,
            "abandonment_timeout must exceed defer_window — a slow legitimate "
            "close cycle must not be misclassified as abandoned",
        )

    def test_defer_branch_uses_defer_window_constant(self):
        """The Step 4b defer branch in run() must pass the defer-window constant.

        Pinned structurally by inspecting the run() source: the defer branch
        must call the age-check helper with _CLOSE_CYCLE_DEFER_WINDOW_SEC
        (not the abandonment constant, which is a substantially longer
        timescale meant for a different purpose).
        """
        run_src = inspect.getsource(gate.run)
        self.assertIn(
            "_CLOSE_CYCLE_DEFER_WINDOW_SEC",
            run_src,
            "run()'s defer branch must reference _CLOSE_CYCLE_DEFER_WINDOW_SEC",
        )
        self.assertIn(
            "_marker_age_under",
            run_src,
            "run() must delegate the age check to the shared _marker_age_under helper",
        )

    def test_abandonment_branch_uses_abandonment_constant(self):
        """The _record_bypass abandonment guard must pass the abandonment constant."""
        bypass_src = inspect.getsource(gate._record_bypass)
        self.assertIn(
            "_CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC",
            bypass_src,
            "_record_bypass must reference _CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC",
        )
        self.assertIn(
            "_marker_age_under",
            bypass_src,
            "_record_bypass must delegate the age check to _marker_age_under",
        )

    def test_shared_age_helper_collapses_duplicate_wrappers(self):
        """A single _marker_age_under helper backs both branches.

        The defer and abandonment paths previously had near-duplicate one-line
        wrappers (_marker_within_defer_window, _marker_within_abandonment_window)
        differing only by the constant — a fix to one had to be mirrored in
        the other or the two branches would silently diverge. Pin the single
        helper so future divergence is impossible.
        """
        self.assertTrue(
            hasattr(gate, "_marker_age_under"),
            "close_cycle_stop_gate must expose _marker_age_under as the single "
            "age-check helper for both defer and abandonment branches",
        )
        self.assertFalse(
            hasattr(gate, "_marker_within_defer_window"),
            "_marker_within_defer_window wrapper must be removed in favor of "
            "_marker_age_under(..., _CLOSE_CYCLE_DEFER_WINDOW_SEC)",
        )
        self.assertFalse(
            hasattr(gate, "_marker_within_abandonment_window"),
            "_marker_within_abandonment_window wrapper must be removed in favor of "
            "_marker_age_under(..., _CLOSE_CYCLE_ABANDONMENT_TIMEOUT_SEC)",
        )

    def test_legacy_unified_constant_removed(self):
        """The shared _CLOSE_CYCLE_AGE_THRESHOLD_SEC must be gone.

        Leaving the legacy constant in place would invite future code to
        reach back for the wrong knob; remove cleanly.
        """
        self.assertFalse(
            hasattr(gate, "_CLOSE_CYCLE_AGE_THRESHOLD_SEC"),
            "legacy _CLOSE_CYCLE_AGE_THRESHOLD_SEC must be removed in favor "
            "of the split constants",
        )


if __name__ == "__main__":
    unittest.main()
