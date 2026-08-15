#!/usr/bin/env python3
"""Tests for review_flag_cli.py.

The close-skill Step 4b runs /code-review via the Workflow tool (async), whose
completion does NOT fire review_cycle_done (a PostToolUse:Skill|Agent hook), so
simplify_done is never set on its own. Step 4b calls this CLI to set the flag
when it LAUNCHES the workflow, so:
  - close_cycle_stop_gate defers during the async review window (review_mid_cycle
    True), and
  - the xp-quality-review preload emits MODE=consume-findings for the findings.
The flag is keyed via identity.review_flags_key, and so is every other read,
write and clear of the flags. The first class below pins that agreement across
the writer, the reader and the clear.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import markers
import review_flag_cli
import review_records
from conftest import _HookTestCase, _make_stop_input
from event_schema import STATUS_ACTION_SIMPLIFY_COMPLETE, event_action

_WATERMARK = "test-review-flag-cli"


class TestTheWriterAndTheGateAgreeOnTheKey(_HookTestCase):
    """The flag this CLI writes must be the flag the close gate reads — and
    the flag the review's completion clears.

    The cycle has writers with no hook payload to resolve from (this CLI) and
    writers whose payload agent_id names someone other than the cycle's owner
    (`subagent_stop`, where it names the subagent). Keying any site off the
    payload therefore splits one checkout's cycle in two, and the second half
    of that split is the dangerous one: a set flag whose clear lands on the
    other record stays set, so the gate's DEFER never ends and the close
    finishes with no close-reviewer nudge at all.

    Nothing tested the pair. The close-gate suites arm the flag by calling the
    READER's own resolver, and `_make_stop_input` supplies `agent_id="main"`,
    which happens to equal the cwd fallback — so every existing test sits on
    the coincidence that hides the divergence.
    """

    def _launch_step_4b(self) -> None:
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )

    def _quality_review_completes(self, agent_id: str) -> None:
        """The PostToolUse leg that ends Step 4b, under a divergent payload.

        The reviewer's SubagentStop, not either PostToolUse: both of those
        fire when their tool call returns, which is at launch.
        """
        from unittest.mock import patch

        import subagent_stop

        with patch("commits.get_code_files_for_review", return_value=[]):
            subagent_stop.run(
                {
                    "session_id": "t",
                    "agent_id": agent_id,
                    "agent_type": "xp-agents:xp-code-reviewer",
                    "cwd": ".",
                    "last_assistant_message": "Done",
                },
                smm_dir=self.smm_dir,
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
        """A Stop payload carrying a platform agent_id must still find the
        CLI's flag; missing it BLOCKS the agent mid-review with no way forward
        until the marker ages out."""
        self._launch_step_4b()

        self.assertIsNone(
            self._stop(agent_id="subagent-abc"),
            "the gate must find the CLI's flag whatever agent_id the payload "
            "carries — a missed defer blocks an agent mid-review",
        )

    def test_the_defer_ends_when_the_review_completes_under_another_agent_id(self):
        """The clear must land on the record the CLI wrote, not beside it.

        A quality-review completion whose payload names a different agent must
        still end the cycle. If it writes quality_review_done elsewhere, the
        CLI's record stays mid-cycle for good and the gate defers away every
        remaining Stop — the close ends with its reviewer never nudged.
        """
        self._launch_step_4b()
        self._quality_review_completes(agent_id="subagent-abc")

        self.assertIsNotNone(
            self._stop(agent_id="subagent-abc"),
            "Step 4b is over — the gate must resume nudging xp-close-reviewer",
        )

    def test_a_close_with_no_step_4b_in_flight_still_blocks(self):
        """Non-vacuity: the pair above must not pass by never blocking."""
        self.assertIsNotNone(self._stop(agent_id="subagent-abc"))


class TestTheCliSubstitutesForTheHookExactly(unittest.TestCase):
    """The CLI's lifecycle entry must equal the hook leg it stands in for.

    The CLI exists because a Workflow completion does not fire
    review_cycle_done, so retro_metrics would not count the close-time review.
    That only holds while the two emit the SAME action and content — a drift
    makes the substitute counted as a different thing, or not at all.

    This was a "keep X in sync with Y" comment, which is a rule with nobody
    checking it.
    """

    def test_the_simplify_leg_matches_the_hook_it_substitutes_for(self):
        import review_cycle_done

        self.assertEqual(
            review_flag_cli._FLAG_LIFECYCLE["simplify_done"],
            review_cycle_done._TARGET_LIFECYCLE[review_cycle_done._TARGET_SIMPLIFY],
        )

    def test_the_flag_name_matches_the_hook_it_substitutes_for(self):
        import review_cycle_done

        self.assertIn(
            review_cycle_done._TARGET_FLAG[review_cycle_done._TARGET_SIMPLIFY],
            review_flag_cli._FLAG_LIFECYCLE,
        )

    def test_the_cli_covers_only_the_async_leg(self):
        """Non-vacuity: an equality over an empty table proves nothing, and
        the quality-review leg deliberately has no CLI substitute — it still
        launches via the Skill tool, so the hook sets it."""
        self.assertEqual(set(review_flag_cli._FLAG_LIFECYCLE), {"simplify_done"})


class TestReviewFlagCli(_HookTestCase):
    """review_flag_cli sets a review-cycle flag for the cwd-resolved agent_id."""

    def test_sets_simplify_done_for_main_cwd(self):
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
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
        self.assertFalse(review_records.review_mid_cycle(self.smm_dir, "main"))
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )
        # simplify_done set + quality_review_done unset => mid-cycle => the close
        # stop-gate defers during the async /code-review workflow window.
        self.assertTrue(review_records.review_mid_cycle(self.smm_dir, "main"))

    def test_rejects_unknown_flag(self):
        with self.assertRaises(SystemExit):
            review_flag_cli.main(
                ["--smm-dir", str(self.smm_dir), "--cwd", ".", "bogus_flag"]
            )


if __name__ == "__main__":
    unittest.main()
