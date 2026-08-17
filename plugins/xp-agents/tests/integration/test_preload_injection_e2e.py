#!/usr/bin/env python3
"""Capstone: does injected state reach a MODEL's context, on both harnesses?

Sprint-007 replaced every skill's preload channel with one hook-side injection
handler and deleted the `!` `SKILL.md` lines, so there is no second channel to
fall back on. Everything shipped before this file proves the mechanism up to the
PROCESS boundary — a real subprocess and a real `hookSpecificOutput` envelope —
and concern 789c6f3f6ed0 exists because that was read as having discharged the
remaining claim and had not. Risk a48453feb189 is the same gap as a risk.

## What this file adds that no other suite can see

`tests/hooks/test_preload_injection.py` already drives this handler against a
scratch plugin root and asserts the envelope. It is not duplicated here. What is
only measurable at this layer:

- **The token exists in no file.** The preload COMPUTES a digest of a seed, so
  the literal value is on no disk anywhere — which is what makes "it reached the
  model" mean something. A recorded marker would be greppable.
- **The fixture the LIVE rows use is itself pinned.** The dual-manifest plugin
  below is the one a real harness loads, so a shape error in it would otherwise
  surface as a mysterious live failure rather than as a red hermetic row.
- **Three states, not two.** A firing probe sits beside the handler in the
  manifest so a live run can tell *fired and injected*, *fired and injected
  nothing*, and *never fired* apart. Without it AC3's not-measured verdict is
  indistinguishable from a negative.
- **The plugin's NAME is load-bearing**, and measured: `tool_input.skill` arrives
  plugin-qualified, and `target_routing.strip_our_namespace` returns None for any
  namespace but ours, so a differently-named fixture injects nothing and says so
  nowhere. Pinned below rather than left as a comment.

## What it deliberately does NOT re-run

The handler's six recorded quiet-failure requirements (preload run in the session
cwd, resolved via `skill_preload_map`, heartbeat written first, nothing injected
on failure) are held by `tests/hooks/test_preload_injection.py` and
`test_preload_injection_shell_read.py`. The per-preload marker table is
`_preload_delivery_fixtures.py`. Re-asserting any of them here would buy nothing
and cost a second place to keep true.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import preload_injection
from _bases import _AssertNotNoneMixin, _IntegrationTestCase
from _capstone_plugin import (
    DELIVERED,
    FIRING_LOG_ENV,
    GUARD_ENV,
    LIVE_ENV,
    NOT_MEASURED,
    NOT_MEASURED_PREFIX,
    OUR_PLUGIN_NAME,
    SECOND_HARNESS_PLUGIN_NAME,
    SEED_ENV,
    WITHHELD,
    ModelRun,
    build_capstone_plugin,
    child_env,
    install_second_harness,
    live_gate_reason,
    requires_live,
    run_first_harness,
    run_second_harness,
    verdict,
)


def _drive_handler(
    fixture, smm_dir: Path, payload: dict, *, extra_env: dict | None = None
):
    """Run the REAL handler as a real process and return (rc, stdout, stderr).

    A subprocess rather than an in-process call because the envelope is the thing
    under test: `run()` returns a string, and it is `__main__` that decides
    whether anything is emitted at all.

    `CLAUDE_PLUGIN_ROOT` is how the fixture is selected, and it is measured
    (discovery 46f3b9ce1447) that a real harness sets exactly this per-plugin —
    so the hermetic rows and the live rows share one selection mechanism instead
    of two.

    The fixture's own env carries the seed, which is the ONLY place it lives —
    keeping it out of every file is what makes the token ungreppable. `extra_env`
    overrides it, so a caller can withhold the seed deliberately.
    """
    import os

    env = {
        **os.environ,
        **fixture.env(),
        "CLAUDE_PLUGIN_ROOT": str(fixture.plugin_dir),
        "SMM_DIR": str(smm_dir),
        **(extra_env or {}),
    }
    completed = subprocess.run(
        [sys.executable, str(Path(preload_injection.__file__))],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    return completed.returncode, completed.stdout, completed.stderr


class TestTheCapstoneFixtureDeliversAComputedToken(_IntegrationTestCase):
    """The fixture the live rows depend on, proved before any model call."""

    def setUp(self):
        super().setUp()
        self.fixture = build_capstone_plugin(Path(self.tmpdir) / "capstone")

    def _skill_payload(self) -> dict:
        return {
            "tool_name": "Skill",
            "tool_input": {"skill": f"{OUR_PLUGIN_NAME}:{self.fixture.skill_name}"},
            "cwd": str(self.tmpdir),
        }

    def test_the_skill_leg_injects_the_computed_token(self):
        """The first harness's leg: identity arrives as `tool_input.skill`."""
        rc, out, err = _drive_handler(
            self.fixture, Path(self.smm_dir), self._skill_payload()
        )

        self.assertEqual(rc, 0, err)
        self.assertIn("additionalContext", out)
        self.assertIn(self.fixture.expected_token, out)

    def test_the_shell_read_leg_injects_it_too(self):
        """The second harness's leg: identity arrives inside a read command.

        Registered only in the derived manifest, but the handler supports it on
        either — so it is driven here directly rather than through a manifest.
        """
        rc, out, err = _drive_handler(
            self.fixture,
            Path(self.smm_dir),
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"cat {self.fixture.skill_body}"},
                "cwd": str(self.tmpdir),
            },
        )

        self.assertEqual(rc, 0, err)
        self.assertIn(self.fixture.expected_token, out)

    def test_a_missing_seed_injects_nothing_not_a_constant(self):
        """The silent-pass channel this fixture must not have.

        Digesting an absent seed would yield `sha256("")` — the SAME token for
        every fixture — so a row asserting "a token arrived" would pass with the
        seed never delivered. This was a real bug in the first draft: both legs
        injected `e3b0c44298fc1c14` and looked healthy. The preload refuses
        instead, and a refusing preload must inject nothing at all.
        """
        rc, out, err = _drive_handler(
            self.fixture,
            Path(self.smm_dir),
            self._skill_payload(),
            extra_env={"XP_CAPSTONE_SEED": ""},
        )

        self.assertEqual(rc, 0, err)
        self.assertEqual(out.strip(), "")

    def test_the_literal_token_is_written_nowhere(self):
        """AC1's "present in no file", checked instead of asserted in prose.

        The preload computes the digest, so only the SEED is ever stored. A model
        that greps for the token finds nothing — which is what stops a live pass
        from being explainable by a file read.
        """
        haystacks = [self.fixture.root, Path(self.tmpdir)]
        for root in haystacks:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                try:
                    text = path.read_text(errors="ignore")
                except OSError:
                    continue
                self.assertNotIn(
                    self.fixture.expected_token,
                    text,
                    f"the literal token is readable at {path} — a live pass "
                    "would then be explainable without injection",
                )

    def test_a_seedless_preload_would_not_pass_by_accident(self):
        """Non-vacuity of the token itself: a different seed yields a different
        token, so the assertions above cannot be satisfied by a constant."""
        other = build_capstone_plugin(Path(self.tmpdir) / "capstone-two")

        self.assertNotEqual(self.fixture.expected_token, other.expected_token)


class TestBothManifestsCarryWhatEachHarnessReads(_IntegrationTestCase):
    """A shape error here surfaces live as "the hook never fired", which is the
    one outcome AC3 must not silently absorb."""

    def setUp(self):
        super().setUp()
        self.fixture = build_capstone_plugin(Path(self.tmpdir) / "capstone")

    def test_the_plugin_is_named_ours_because_the_namespace_check_demands_it(self):
        """Measured (discovery 46f3b9ce1447): `tool_input.skill` arrives
        plugin-qualified, and `strip_our_namespace` returns None for any other
        namespace — so a renamed fixture injects nothing and reports nothing.
        Pinned so a future rename fails here rather than in a live row.
        """
        manifest = json.loads(
            (self.fixture.plugin_dir / ".claude-plugin" / "plugin.json").read_text()
        )

        self.assertEqual(manifest["name"], OUR_PLUGIN_NAME)

    def test_the_first_harness_manifest_registers_the_skill_trigger(self):
        entries = self.fixture.hook_entries(".claude-plugin")
        matchers = [e.get("matcher") for e in entries]

        self.assertIn("Skill", matchers)

    def test_the_derived_manifest_adds_the_shell_read_trigger(self):
        """The second harness has no skill tool call at all, so without this
        entry that harness has no trigger and measures nothing."""
        derived = json.loads(
            (self.fixture.plugin_dir / ".codex-plugin" / "plugin.json").read_text()
        )
        entries = self.fixture.hook_entries(".codex-plugin")
        matchers = [e.get("matcher") for e in entries]

        self.assertEqual(derived["hooks"], "./hooks/hooks.codex.json")
        self.assertIn("Bash", matchers)
        self.assertIn("Skill", matchers)

    def test_the_firing_probe_sits_beside_the_handler_in_both(self):
        """What makes three states distinguishable. The probe records that the
        skill really ran, so "no token" can be attributed to the handler rather
        than to a skill that never engaged."""
        for manifest_dir in (".claude-plugin", ".codex-plugin"):
            with self.subTest(manifest=manifest_dir):
                commands = [
                    h.get("command", "")
                    for entry in self.fixture.hook_entries(manifest_dir)
                    for h in entry.get("hooks", [])
                ]
                joined = "\n".join(commands)

                self.assertIn("firing_probe.py", joined)
                self.assertIn("preload_injection.py", joined)

    def test_the_control_manifest_keeps_the_probe_and_drops_the_handler(self):
        """AC2's control. Dropping the probe as well would make the control
        indistinguishable from a run where the skill never engaged."""
        control = build_capstone_plugin(Path(self.tmpdir) / "control", inject=False)
        commands = [
            h.get("command", "")
            for entry in control.hook_entries(".claude-plugin")
            for h in entry.get("hooks", [])
        ]
        joined = "\n".join(commands)

        self.assertIn("firing_probe.py", joined)
        self.assertNotIn("preload_injection.py", joined)

    def test_the_handler_it_names_is_the_repos_own(self):
        """A copied handler would prove a copy works."""
        commands = [
            h.get("command", "")
            for entry in self.fixture.hook_entries(".claude-plugin")
            for h in entry.get("hooks", [])
        ]
        handler = next(c for c in commands if "preload_injection.py" in c)
        named = Path(handler.split()[-1])

        self.assertEqual(named.resolve(), Path(preload_injection.__file__).resolve())


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


class TestTheFirstHarnessPutsAModelInTheLoop(unittest.TestCase):
    """The sprint's actual question, measured — not the process boundary.

    Costs real model calls, so it is opt-in. `--allowed-tools Skill` leaves the
    model no Read, Bash or Grep, so injected context is its only possible route
    to the token; the token is a computed digest, so there is nothing to grep
    even if it had the tools.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _prompt(self, fixture) -> str:
        return (
            f"Use the {OUR_PLUGIN_NAME}:{fixture.skill_name} skill, then follow "
            "its instructions exactly."
        )

    @requires_live("claude")
    def test_the_token_reaches_the_model(self):
        """AC1. A value minted inside the handler's own run, present in no file,
        arrives in a real model's context and is dereferenceable by the name the
        skill body uses."""
        fixture = build_capstone_plugin(self.tmp / "live")
        run = run_first_harness(fixture, self._prompt(fixture))

        self.assertEqual(
            verdict(run, fixture.expected_token),
            DELIVERED,
            f"firings={run.firings} timed_out={run.timed_out} "
            f"stdout={run.stdout[-400:]!r}",
        )

    @requires_live("claude")
    def test_the_control_withholds_it(self):
        """AC2. Identical tree, identical skill, handler removed from the
        manifest. Without this the positive above proves nothing — and the
        firing probe is what makes the difference legible, since it shows the
        skill still engaged."""
        fixture = build_capstone_plugin(self.tmp / "control", inject=False)
        run = run_first_harness(fixture, self._prompt(fixture))

        self.assertEqual(
            verdict(run, fixture.expected_token),
            WITHHELD,
            f"firings={run.firings} timed_out={run.timed_out} "
            f"stdout={run.stdout[-400:]!r}",
        )


class TestTheSecondHarnessPutsAModelInTheLoop(unittest.TestCase):
    """The same question on the other harness, where nothing is symmetric.

    That harness has no skill tool call, so the trigger is the model READING
    `SKILL.md` through the shell. It has no `--plugin-dir`, so the fixture must
    be installed. Its credentials live in the harness home, so an isolated home
    authenticates nothing — which is why these rows install into the developer's
    REAL home under distinct names and remove themselves afterwards.

    The residual, stated rather than implied: this model has shell access, so it
    could in principle read the preload and recompute the digest itself.
    Impossibility is not available here, and the control is what carries the
    weight — with the handler removed the token does not arrive.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _fixture(self, name: str, *, inject: bool = True):
        return build_capstone_plugin(
            self.tmp / name,
            inject=inject,
            plugin_name=SECOND_HARNESS_PLUGIN_NAME,
        )

    @requires_live("codex")
    def test_the_installed_copy_carries_the_shell_read_trigger(self):
        """Without this entry the harness has no trigger and the rows below
        would report not-measured for a reason that looks like delivery."""
        fixture = self._fixture("installed")
        installed_root = install_second_harness(fixture, self.addCleanup)

        declared = json.loads(
            (installed_root / ".codex-plugin" / "plugin.json").read_text()
        )["hooks"]
        entries = json.loads((installed_root / declared.lstrip("./")).read_text())
        matchers = [e.get("matcher") for e in entries["hooks"]["PreToolUse"]]

        self.assertIn("Bash", matchers)

    @requires_live("codex")
    def test_the_token_reaches_the_model(self):
        """AC1 on the second harness."""
        fixture = self._fixture("live")
        installed_root = install_second_harness(fixture, self.addCleanup)
        run = run_second_harness(fixture, installed_root)

        self.assertEqual(
            verdict(run, fixture.expected_token),
            DELIVERED,
            f"firings={run.firings} timed_out={run.timed_out} "
            f"stdout={run.stdout[-400:]!r}",
        )

    @requires_live("codex")
    def test_the_control_withholds_it(self):
        """AC2 on the second harness, and here it is load-bearing rather than a
        redundant check — see the class docstring's residual."""
        fixture = self._fixture("control", inject=False)
        installed_root = install_second_harness(fixture, self.addCleanup)
        run = run_second_harness(fixture, installed_root)

        self.assertEqual(
            verdict(run, fixture.expected_token),
            WITHHELD,
            f"firings={run.firings} timed_out={run.timed_out} "
            f"stdout={run.stdout[-400:]!r}",
        )


if __name__ == "__main__":
    unittest.main()
