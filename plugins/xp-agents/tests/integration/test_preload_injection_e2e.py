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

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import preload_injection
from _bases import _IntegrationTestCase
from _capstone_drivers import (
    DELIVERED,
    SECOND_HARNESS_PLUGIN_NAME,
    WITHHELD,
    install_second_harness,
    requires_live,
    run_first_harness,
    run_second_harness,
    verdict,
)
from _capstone_plugin import OUR_PLUGIN_NAME, build_capstone_plugin


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

        Walked AFTER a real handler run rather than over a freshly built tree:
        the claim is that DELIVERING the token writes it nowhere, and a tree
        nothing has run against cannot say that. The SMM dir is a haystack for
        the same reason — the handler writes a heartbeat and a claim marker
        there, and it lives outside the repo temp dir.
        """
        _, out, err = _drive_handler(
            self.fixture, Path(self.smm_dir), self._skill_payload()
        )
        self.assertIn(self.fixture.expected_token, out, err)

        haystacks = [self.fixture.root, Path(self.tmpdir), Path(self.smm_dir)]
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
        _home, installed_root = install_second_harness(fixture, self.addCleanup)

        declared = json.loads(
            (installed_root / ".codex-plugin" / "plugin.json").read_text()
        )["hooks"]
        entries = json.loads((installed_root / declared.removeprefix("./")).read_text())
        matchers = [e.get("matcher") for e in entries["hooks"]["PreToolUse"]]

        self.assertIn("Bash", matchers)

    @requires_live("codex")
    def test_the_token_reaches_the_model(self):
        """AC1 on the second harness."""
        fixture = self._fixture("live")
        home, installed_root = install_second_harness(fixture, self.addCleanup)
        run = run_second_harness(fixture, home, installed_root)

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
        home, installed_root = install_second_harness(fixture, self.addCleanup)
        run = run_second_harness(fixture, home, installed_root)

        self.assertEqual(
            verdict(run, fixture.expected_token),
            WITHHELD,
            f"firings={run.firings} timed_out={run.timed_out} "
            f"stdout={run.stdout[-400:]!r}",
        )


if __name__ == "__main__":
    unittest.main()
