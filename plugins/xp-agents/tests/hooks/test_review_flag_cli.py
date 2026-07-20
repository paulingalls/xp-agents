#!/usr/bin/env python3
"""Tests for review_flag_cli.py.

The close-skill Step 4b runs /code-review via the Workflow tool (async), whose
completion does NOT fire review_cycle_done (a PostToolUse:Skill|Agent hook), so
simplify_done is never set on its own. Step 4b calls this CLI to set the flag
when it LAUNCHES the workflow, so:
  - close_cycle_stop_gate defers during the async review window (review_mid_cycle
    True), and
  - the xp-quality-review preload emits MODE=consume-findings for the findings.
The flag is keyed on the cwd-resolved agent_id — the same resolution the readers
(review_mode.py, close_cycle_stop_gate.py) use.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import markers
import review_flag_cli
from conftest import _HookTestCase
from event_schema import STATUS_ACTION_SIMPLIFY_COMPLETE, event_action

_WATERMARK = "test-review-flag-cli"


class TestReviewFlagCli(_HookTestCase):
    """review_flag_cli sets a review-cycle flag for the cwd-resolved agent_id."""

    def test_sets_simplify_done_for_main_cwd(self):
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )
        cycle = markers.read_review_cycle(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_emits_lifecycle_event_for_retro_metrics(self):
        # The async-workflow /code-review can't fire review_cycle_done, so the
        # CLI must emit the same SIMPLIFY_COMPLETE action event retro_metrics
        # counts — else the close-time review is invisible in the retro.
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK)
        actions = [event_action(e) for e in events]
        self.assertIn(STATUS_ACTION_SIMPLIFY_COMPLETE, actions)

    def test_flag_makes_close_gate_defer_mid_cycle(self):
        self.assertFalse(markers.review_mid_cycle(self.smm_dir, "main"))
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )
        # simplify_done set + quality_review_done unset => mid-cycle => the close
        # stop-gate defers during the async /code-review workflow window.
        self.assertTrue(markers.review_mid_cycle(self.smm_dir, "main"))

    def test_rejects_unknown_flag(self):
        with self.assertRaises(SystemExit):
            review_flag_cli.main(
                ["--smm-dir", str(self.smm_dir), "--cwd", ".", "bogus_flag"]
            )


if __name__ == "__main__":
    unittest.main()
