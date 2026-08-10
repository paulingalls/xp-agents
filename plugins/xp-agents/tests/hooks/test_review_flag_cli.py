#!/usr/bin/env python3
"""Tests for review_flag_cli.py.

The close-skill Step 4b runs /code-review via the Workflow tool (async), whose
completion does NOT fire review_cycle_done (a PostToolUse:Skill|Agent hook), so
simplify_done is never set on its own. Step 4b calls this CLI to set the flag
when it LAUNCHES the workflow, so:
  - close_cycle_stop_gate defers during the async review window (review_mid_cycle
    True), and
  - the xp-quality-review preload emits MODE=consume-findings for the findings.
The flag is keyed on the cwd-resolved agent_id. review_mode.py reads it that
way; close_cycle_stop_gate does NOT — it resolves from the hook payload first,
so it reads under both keys rather than one. That divergence is the contract
the first class below pins.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import markers
import review_flag_cli
from conftest import _HookTestCase, _make_stop_input
from event_schema import STATUS_ACTION_SIMPLIFY_COMPLETE, event_action

_WATERMARK = "test-review-flag-cli"


class TestTheWriterAndTheGateAgreeOnTheKey(_HookTestCase):
    """The flag this CLI writes must be the flag the close gate reads.

    They resolve the key differently and neither can simply adopt the other's
    resolution: the flag has three writers across two resolutions — the two
    hooks (`subagent_stop`, `review_cycle_done`) go through
    `resolve_agent_id(input_data)`, this CLI through
    `resolve_agent_id_from_cwd`, and the quality-review preload reads it the
    CLI's way while the gate reads it the hooks' way. Swapping either side
    just moves the mismatch onto the other pair.

    Nothing tested the pair. The close-gate suites arm the flag by calling the
    READER's own resolver, and `_make_stop_input` supplies `agent_id="main"`,
    which happens to equal the writer's cwd fallback — so every existing test
    sits on the coincidence that hides the divergence.
    """

    def _launch_step_4b(self) -> None:
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )

    def _stop(self, **kwargs) -> object:
        import close_cycle_stop_gate

        markers.marker_write(self.smm_dir, markers.CLOSE_CYCLE_ACTIVE, "1")
        return close_cycle_stop_gate.run(
            _make_stop_input(**kwargs), smm_dir=self.smm_dir
        )

    def test_the_gate_defers_on_the_flag_the_cli_wrote(self):
        """The agreeing path: a payload whose agent_id matches the cwd fallback."""
        self._launch_step_4b()

        self.assertIsNone(
            self._stop(), "the close gate must defer while Step 4b is in flight"
        )

    def test_the_gate_defers_even_when_the_payload_names_a_platform_agent(self):
        """The divergence, and why it is not hypothetical.

        `resolve_agent_id` returns any non-empty platform `agent_id` verbatim
        and never consults cwd, so a Stop payload carrying one sends the gate
        looking for a key this CLI never wrote. It then BLOCKS mid-review
        instead of deferring, and the agent has no way forward until the
        marker ages out.
        """
        self._launch_step_4b()

        self.assertIsNone(
            self._stop(agent_id="subagent-abc"),
            "the gate must find the CLI's flag whatever agent_id the payload "
            "carries — a missed defer blocks an agent mid-review",
        )

    def test_a_close_with_no_step_4b_in_flight_still_blocks(self):
        """Non-vacuity: the pair above must not pass by never blocking."""
        self.assertIsNotNone(self._stop(agent_id="subagent-abc"))


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
