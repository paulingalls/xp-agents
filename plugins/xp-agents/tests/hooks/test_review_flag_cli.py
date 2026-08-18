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

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(
    0,
    str(
        Path(__file__).parent.parent.parent / "skills" / "xp-quality-review" / "scripts"
    ),
)

import _common
import markers
import review_flag_cli
import review_mode
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
        """The leg that ends Step 4b, under a divergent payload.

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

    def test_the_default_flag_is_the_one_the_table_holds(self):
        """The positional is optional so the close prose need not spell an
        internal state field — naming one in instructions that ship to every
        project is what the prose vocabulary pins discourage, and the promotion
        of this flag into the corpus-wide ban is what made that concrete.

        A default that drifted out of the table would take the CLI's whole
        purpose with it: argparse would reject the prose's own invocation, and
        the close would arm nothing.
        """
        self.assertIn(review_flag_cli._DEFAULT_FLAG, review_flag_cli._FLAG_LIFECYCLE)

    def test_the_cli_covers_only_the_async_leg(self):
        """Non-vacuity: an equality over an empty table proves nothing, and
        the quality-review leg deliberately has no CLI substitute — a
        prose-invoked leg would make the commit gate's own flag settable
        without a review; `review_cycle_legs` sets it from the reviewer's
        SubagentStop instead."""
        self.assertEqual(set(review_flag_cli._FLAG_LIFECYCLE), {"simplify_done"})


class TestDisarmingAnAbandonedReview(_HookTestCase):
    """Step 4b arms the flag at LAUNCH, so an errored or abandoned review leaves
    it set with nothing able to clear it.

    Only a landed commit clears the cycle (`end_review_cycle`, off the
    reviewer's SubagentStop), and the arm's whole point is that the launcher
    reaches no completion hook. So a workflow that dies takes the next
    `/xp-quality-review` into consume-findings mode with nothing to consume: it
    asks for a findings list that does not exist, and the reviewer's self-find
    branch — the one that would have found the bugs itself — never runs.

    The assertions below are on what the CLOSE SKILL observes, not on the
    marker. A test that reads back the flag it just wrote proves the CLI can
    write a flag; it says nothing about the mode the next preload emits, which
    is the behaviour the disarm exists to restore.
    """

    def _arm(self) -> None:
        # No flag argument, which is the form the shipped prose uses — see
        # test_the_default_flag_is_the_one_the_table_holds.
        review_flag_cli.main(["--smm-dir", str(self.smm_dir), "--cwd", "."])

    def _disarm(self) -> None:
        review_flag_cli.main(["--smm-dir", str(self.smm_dir), "--cwd", ".", "--disarm"])

    def _mode(self, cwd: str = ".") -> str:
        argv = ["review_mode", "--smm-dir", str(self.smm_dir), "--cwd", cwd]
        buf = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stdout(buf):
            review_mode.main()
        return buf.getvalue().strip()

    def _actions(self) -> list[str | None]:
        events = _common.read_events_locked(self.smm_dir, _WATERMARK)
        return [event_action(e) for e in events]

    def test_the_next_quality_review_is_self_find_again(self):
        self._arm()
        self.assertEqual(
            self._mode(),
            review_mode.CONSUME_FINDINGS,
            "non-vacuity: the arm must reach the preload, or the disarm below "
            "would pass against a mode that was never consume-findings",
        )

        self._disarm()

        self.assertEqual(self._mode(), review_mode.SELF_FIND)

    def test_the_close_gate_stops_deferring_on_a_review_that_is_not_coming(self):
        """The other consumer of the same flag. Left armed, `review_mid_cycle`
        stays True and the close's Stop gate defers every remaining Stop, so the
        close ends without ever nudging its close-reviewer."""
        self._arm()
        self.assertTrue(review_records.review_mid_cycle(self.smm_dir, "main"))

        self._disarm()

        self.assertFalse(review_records.review_mid_cycle(self.smm_dir, "main"))

    def test_an_armed_then_abandoned_review_leaves_no_completion_at_all(self):
        """A review that launched and died completed nothing, so the log must
        say nothing about one.

        This asserted `== 1` while the ARM emitted the lifecycle event, which
        was the strongest claim available then and still let a disarmed cycle
        count as a completed review in the retro. With the emission moved to
        `--complete` the honest number is zero, and the assertion says so.
        """
        self._arm()
        self._disarm()

        self.assertEqual(
            self._actions().count(STATUS_ACTION_SIMPLIFY_COMPLETE),
            0,
            "nothing completed, so nothing may be counted as completed",
        )

    def test_disarming_leaves_the_commit_gate_flag_alone(self):
        """`quality_review_done` is the flag the per-increment COMMIT gate reads,
        and this CLI is prose-invoked. Clearing it from here would let anything
        able to run a command re-open a gate a real review had closed — the hole
        `_FLAG_LIFECYCLE`'s comment refuses a set-leg for."""
        review_records.set_review_flag(self.smm_dir, "main", "quality_review_done")
        self._arm()

        self._disarm()

        flags = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(flags["quality_review_done"])

    def test_disarming_a_cycle_that_was_never_armed_is_a_no_op(self):
        """Step 4b's error path cannot always know whether the arm landed — the
        launch may be what failed. Disarming unconditionally must be safe."""
        self._disarm()

        self.assertEqual(self._mode(), review_mode.SELF_FIND)
        self.assertNotIn(STATUS_ACTION_SIMPLIFY_COMPLETE, self._actions())

    def test_withdrawing_and_completing_the_same_review_is_refused(self):
        """The two outcomes are opposites, so asking for both is a caller bug
        and has to say so.

        It used to be accepted and resolved silently in `--complete`'s favour:
        the flag was left alone and a completion event was written for the
        review the caller was trying to withdraw. That is the same wrong count
        the arm/emit split exists to prevent, reachable through a typo rather
        than through the sequence. argparse exits 2 on a mutually exclusive
        pair, so nothing is written at all.
        """
        with self.assertRaises(SystemExit) as raised:
            review_flag_cli.main(
                [
                    "--smm-dir",
                    str(self.smm_dir),
                    "--cwd",
                    ".",
                    "--disarm",
                    "--complete",
                ]
            )

        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn(STATUS_ACTION_SIMPLIFY_COMPLETE, self._actions())


class TestReviewFlagCli(_HookTestCase):
    """review_flag_cli sets a review-cycle flag for the cwd-resolved agent_id."""

    def test_sets_simplify_done_for_main_cwd(self):
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "simplify_done"]
        )
        cycle = review_records.read_review_flags(self.smm_dir, "main")
        self.assertTrue(cycle["simplify_done"])

    def test_arming_emits_nothing_because_nothing_has_completed(self):
        """The arm happens at LAUNCH. It used to emit SIMPLIFY_COMPLETE there,
        which said a review had completed at the moment one started — and left
        nothing able to retract it if the review then died.

        Found by the broad review reading its own branch: on the documented
        fallback path the count was wrong every time. The by-hand arm emitted
        one event, the disarm deliberately emits none, and then the fallback
        Skill's PostToolUse emitted a second for the SAME review.
        """
        review_flag_cli.main(["--smm-dir", str(self.smm_dir), "--cwd", "."])
        events = _common.read_events_locked(self.smm_dir, _WATERMARK)
        self.assertNotIn(
            STATUS_ACTION_SIMPLIFY_COMPLETE,
            [event_action(e) for e in events],
        )

    def test_complete_emits_the_event_retro_metrics_counts(self):
        # A Workflow completion fires no hook, so the close says the review
        # finished by running this once its findings are in hand. Same action
        # and content as the hook leg it substitutes for.
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "--complete"]
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK)
        actions = [event_action(e) for e in events]
        self.assertEqual(actions.count(STATUS_ACTION_SIMPLIFY_COMPLETE), 1)

    def test_complete_leaves_the_flag_set_for_the_quality_review(self):
        """`--complete` reports; it does not end the cycle. The quality review
        still has to read consume-findings and consume the findings, and the
        cycle ends where it always did — at the reviewer's SubagentStop."""
        review_flag_cli.main(["--smm-dir", str(self.smm_dir), "--cwd", "."])
        review_flag_cli.main(
            ["--smm-dir", str(self.smm_dir), "--cwd", ".", "--complete"]
        )
        self.assertTrue(review_records.review_mid_cycle(self.smm_dir, "main"))

    def test_the_fallback_sequence_emits_exactly_one_completion(self):
        """arm -> disarm -> the fallback's own hook. The sequence the broad
        review found double-counting, asserted end to end rather than in the
        two halves that each looked fine alone."""
        review_flag_cli.main(["--smm-dir", str(self.smm_dir), "--cwd", "."])
        review_flag_cli.main(["--smm-dir", str(self.smm_dir), "--cwd", ".", "--disarm"])
        # The fallback Skill's PostToolUse leg, which arms AND emits.
        import review_cycle_done

        target = review_cycle_done._TARGET_SIMPLIFY
        action, content = review_cycle_done._TARGET_LIFECYCLE[target]
        _common.append_safe(
            self.smm_dir,
            _common.make_event(
                _common.STATUS,
                "main",
                content,
                working_on=[],
                metadata={"action": action},
            ),
        )
        events = _common.read_events_locked(self.smm_dir, _WATERMARK)
        actions = [event_action(e) for e in events]
        self.assertEqual(
            actions.count(STATUS_ACTION_SIMPLIFY_COMPLETE),
            1,
            "one review, one completion event — the retro counts occurrences",
        )

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
