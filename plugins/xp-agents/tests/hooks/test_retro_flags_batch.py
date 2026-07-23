#!/usr/bin/env python3
"""Tests for the retro batch-size flag (`max_events_to_commit`).

Split from test_retro_flags.py when story-010's pins pushed that file past
the 500-line limit. Everything here is about one flag: its threshold, the
provenance of that threshold, the wording of its message, and the decision
that suppresses it. Threshold evaluation for every OTHER metric stays in
test_retro_flags.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import retro_flags
from test_retro_flags import _healthy_signals


class TestEventsToCommit(unittest.TestCase):
    def test_fires_at_threshold(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = retro_flags.MAX_EVENTS_TO_COMMIT_THRESHOLD
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("max_events_to_commit", names)

    def test_below_threshold(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = retro_flags.MAX_EVENTS_TO_COMMIT_THRESHOLD - 1
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertNotIn("max_events_to_commit", names)


class TestBatchFlagLabelMatchesCounter(unittest.TestCase):
    """AC-3: the message must describe exactly what the counter measured.

    The original defect was a label ("N events between first edit and
    commit") that the counter did not implement. These pins fail if the
    wording drifts from the counter again — including toward the opposite
    error of describing a global, session-wide count.
    """

    def _fire(self, **overrides):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 40
        w.update(overrides)
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        return next(f for f in flags if f["metric"] == "max_events_to_commit")

    def test_message_names_the_agent_measured(self):
        flag = self._fire(max_events_to_commit_agent="worktree-story-003")
        self.assertIn("worktree-story-003", flag["message"])

    def test_message_states_the_first_edit_anchor(self):
        self.assertIn("first code edit", self._fire()["message"])

    def test_message_states_the_test_run_exclusion(self):
        self.assertIn("excluding test runs", self._fire()["message"])

    def test_message_scopes_the_commit_to_that_agent(self):
        """'its own commit' — not any agent's next commit."""
        self.assertIn("its own commit", self._fire()["message"])

    def test_message_survives_a_missing_agent_attribution(self):
        """Degrades to an honest 'one agent', never a KeyError or a lie."""
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 40
        del w["max_events_to_commit_agent"]
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        flag = next(f for f in flags if f["metric"] == "max_events_to_commit")
        self.assertIn("one agent", flag["message"])


class TestBatchThresholdProvenance(unittest.TestCase):
    """AC-4: the threshold is derived from measurement, and stays that way.

    These pins hold the threshold inside the band its recorded sample
    supports — above the sample's p90, at or below its max. That does not
    freeze the exact number, but it does mean a bump outside the measured
    band (the inherited 75, say) cannot land without re-measuring and
    updating BATCH_THRESHOLD_BASIS alongside it.
    """

    def test_basis_records_a_measured_sample(self):
        basis = retro_flags.BATCH_THRESHOLD_BASIS
        self.assertGreater(basis["events"], 0)
        self.assertTrue(basis["closed_intervals"])
        self.assertTrue(basis["source"])

    def test_basis_states_its_sample_honestly(self):
        """A small, post-compaction, one-sprint sample must say so."""
        self.assertTrue(retro_flags.BATCH_THRESHOLD_BASIS["caveat"].strip())

    def test_threshold_sits_above_p90_of_the_measured_sample(self):
        """Quiet on ordinary work — it must not fire on the ninetieth pct."""
        intervals = sorted(retro_flags.BATCH_THRESHOLD_BASIS["closed_intervals"])
        p90 = intervals[round(0.9 * (len(intervals) - 1))]
        self.assertGreater(retro_flags.MAX_EVENTS_TO_COMMIT_THRESHOLD, p90)

    def test_threshold_is_still_reachable(self):
        """A flag that cannot fire is as dishonest as one that always does."""
        intervals = retro_flags.BATCH_THRESHOLD_BASIS["closed_intervals"]
        self.assertLessEqual(retro_flags.MAX_EVENTS_TO_COMMIT_THRESHOLD, max(intervals))


class TestDecisionAwareSuppression(unittest.TestCase):
    def test_max_events_to_commit_suppressed_by_decision(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 80
        flags = retro_flags.evaluate_flags(
            h, w, s, ss, decisions=["retro-try-kickoff-exemption"]
        )
        names = [f["metric"] for f in flags]
        self.assertNotIn("max_events_to_commit", names)

    def test_unrelated_decision_does_not_suppress(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 80
        flags = retro_flags.evaluate_flags(
            h, w, s, ss, decisions=["retro-try-something-else"]
        )
        names = [f["metric"] for f in flags]
        self.assertIn("max_events_to_commit", names)

    def test_other_flags_unaffected_by_kickoff_decision(self):
        h, w, s, ss = _healthy_signals()
        w["unaddressed_concerns"] = 2
        w["max_events_to_commit"] = 80
        flags = retro_flags.evaluate_flags(
            h, w, s, ss, decisions=["retro-try-kickoff-exemption"]
        )
        names = [f["metric"] for f in flags]
        self.assertNotIn("max_events_to_commit", names)
        self.assertIn("unaddressed_concerns", names)

    def test_backward_compat_no_decisions_param(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 80
        flags = retro_flags.evaluate_flags(h, w, s, ss)
        names = [f["metric"] for f in flags]
        self.assertIn("max_events_to_commit", names)

    def test_empty_decisions_list_no_suppression(self):
        h, w, s, ss = _healthy_signals()
        w["max_events_to_commit"] = 80
        flags = retro_flags.evaluate_flags(h, w, s, ss, decisions=[])
        names = [f["metric"] for f in flags]
        self.assertIn("max_events_to_commit", names)


if __name__ == "__main__":
    unittest.main()
