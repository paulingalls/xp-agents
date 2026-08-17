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
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import preload_injection
from _bases import _IntegrationTestCase
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
    import os

    env = {
        **os.environ,
        **fixture.env(),
        "CLAUDE_PLUGIN_ROOT": str(fixture.root),
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
            (self.fixture.root / ".claude-plugin" / "plugin.json").read_text()
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
            (self.fixture.root / ".codex-plugin" / "plugin.json").read_text()
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


if __name__ == "__main__":
    unittest.main()
