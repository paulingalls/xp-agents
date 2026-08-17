#!/usr/bin/env python3
"""The plumbing that keeps the capstone's live rows honest and contained.

Split from `test_preload_injection_e2e.py`, which measures the delivery chain
itself. These rows measure the machinery AROUND that measurement — the gate that
decides whether a live row runs, the classifier that turns a run into a verdict,
and the child environment that stops a spawned model re-entering this suite.

They are here rather than there because they are the rows that must stay cheap
and always-on: none of them spawns anything, so they run on every commit and
every push while the live rows sit behind their opt-in.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from _bases import _AssertNotNoneMixin
from _capstone_drivers import (
    DELIVERED,
    GUARD_ENV,
    LIVE_ENV,
    NOT_MEASURED,
    NOT_MEASURED_PREFIX,
    WITHHELD,
    ModelRun,
    child_env,
    live_gate_reason,
    verdict,
)
from _capstone_plugin import FIRING_LOG_ENV, SEED_ENV, build_capstone_plugin


class TestTheLiveGateCannotReadAsAPass(_AssertNotNoneMixin, unittest.TestCase):
    """AC3 and AC4: an unrun harness is never reported as passing.

    The live rows cost real model calls on two harnesses, so they are opt-in
    (customer decision, answer af6d7b1b0c4d). That makes the gate itself
    load-bearing: a gate that silently took the run branch, or that reported a
    skip as a pass, would leave the sprint's headline claim resting on nothing —
    which is precisely how concern 789c6f3f6ed0 came about.
    """

    def test_no_variable_means_not_measured(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(LIVE_ENV, None)
            reason = self._assert_not_none(live_gate_reason("claude"))

        self.assertIn(LIVE_ENV, reason)

    def test_the_reason_says_not_measured_rather_than_failed(self):
        """AC3's wording. "Not measured" and "measured and absent" are opposite
        findings, and only one of them is evidence about the mechanism."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(LIVE_ENV, None)
            reason = self._assert_not_none(live_gate_reason("claude"))

        self.assertTrue(
            reason.startswith(NOT_MEASURED_PREFIX),
            f"a withheld row must announce itself as not-measured: {reason!r}",
        )

    def test_the_reason_names_the_harness_it_did_not_measure(self):
        """AC4: "the second harness was not measured" is only useful if the row
        says WHICH. A shared reason string would let one harness's skip stand in
        for the other's."""
        with patch.dict(os.environ, {LIVE_ENV: "1"}):
            reasons = {h: live_gate_reason(h) for h in ("claude", "codex")}

        for harness, reason in reasons.items():
            if reason is not None:
                self.assertIn(harness, reason)

    def test_an_absent_harness_is_not_measured_not_passed(self):
        with patch.dict(os.environ, {LIVE_ENV: "1"}):
            reason = self._assert_not_none(
                live_gate_reason("a-harness-that-is-not-installed")
            )

        self.assertTrue(reason.startswith(NOT_MEASURED_PREFIX))

    def test_the_gate_opens_only_when_both_conditions_hold(self):
        with patch.dict(os.environ, {LIVE_ENV: "1"}):
            if shutil.which("claude"):
                self.assertIsNone(live_gate_reason("claude"))
            else:
                self.skipTest("claude not on PATH; the open branch is unreachable")


class TestTheChildEnvironmentCannotRecurse(unittest.TestCase):
    """Safety §1. `_spawn_guard` records what this prevents: a spawned agent came
    up with the plugin loaded, ran the suite as part of its own lifecycle,
    re-entered the test that spawned it, and did it again — ~20 real, billable,
    recursive agents, one alive 22 minutes.

    Environment is INHERITED, so both opt-in variables must be absent from the
    child. `XP_ALLOW_REAL_AGENT_SPAWN` is the dangerous one: it is the guard's own
    escape hatch, so a child that inherited it would spawn with the backstop
    already disarmed. Asserted rather than trusted to the construction, which is
    the same reason `assert_module_skips_without_harness` refuses to ride on an
    inherited sentinel.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fixture = build_capstone_plugin(self.tmp / "capstone")

    def test_neither_opt_in_variable_reaches_the_child(self):
        with patch.dict(os.environ, {LIVE_ENV: "1", GUARD_ENV: "1"}):
            env = child_env(self.fixture)

        self.assertNotIn(LIVE_ENV, env)
        self.assertNotIn(GUARD_ENV, env)

    def test_the_seed_does_reach_the_child(self):
        """The strip must not take the seed with it: a seedless child gets a
        refusing preload, which reads as "delivered nothing" — a false negative
        wearing the same face as a real one."""
        env = child_env(self.fixture)

        self.assertEqual(env.get(SEED_ENV), self.fixture.seed)

    def test_the_firing_log_reaches_the_child(self):
        """Without it the probe cannot record, and the control loses the only
        thing that tells "injected nothing" from "never fired"."""
        env = child_env(self.fixture)

        self.assertEqual(env.get(FIRING_LOG_ENV), str(self.fixture.firing_log))

    def test_the_child_runs_outside_this_repo(self):
        """A child whose cwd is this checkout can reach the suite. The cwd the
        drivers use is the fixture's own temp tree."""
        self.assertFalse(
            str(self.fixture.child_cwd).startswith(str(Path.cwd())),
            "the child's cwd is inside this checkout, so a child with shell "
            "access could re-enter the suite",
        )


class TestNotMeasuredIsNeverANegative(unittest.TestCase):
    """AC3, pinned WITHOUT paying for a model call.

    The branch that only appears when something went wrong is otherwise the one
    branch a green suite never exercises. `verdict` is a pure function precisely
    so this is assertable: a run that never fired, or that died on the clock,
    says nothing about delivery, and recording it as a negative would be a claim
    the run does not support.
    """

    def test_a_handler_that_never_fired_is_not_measured(self):
        run = ModelRun(stdout="", firings=0, timed_out=False)

        self.assertEqual(verdict(run, "abc123"), NOT_MEASURED)

    def test_a_timeout_is_not_measured_even_if_something_fired(self):
        run = ModelRun(stdout="", firings=1, timed_out=True)

        self.assertEqual(verdict(run, "abc123"), NOT_MEASURED)

    def test_a_token_present_after_a_confirmed_firing_is_delivery(self):
        run = ModelRun(stdout="the value is abc123", firings=1, timed_out=False)

        self.assertEqual(verdict(run, "abc123"), DELIVERED)

    def test_a_token_absent_after_a_confirmed_firing_is_withheld(self):
        """The control's expected outcome, and the one that must NOT collapse
        into not-measured: the skill ran and the token did not arrive, which is
        a real finding about the handler."""
        run = ModelRun(stdout="NO-TOKEN", firings=1, timed_out=False)

        self.assertEqual(verdict(run, "abc123"), WITHHELD)

    def test_the_three_outcomes_are_distinct(self):
        """A refactor collapsing two of them would silently turn "we did not
        measure" into "we measured nothing arriving"."""
        self.assertEqual(len({DELIVERED, WITHHELD, NOT_MEASURED}), 3)


if __name__ == "__main__":
    unittest.main()
