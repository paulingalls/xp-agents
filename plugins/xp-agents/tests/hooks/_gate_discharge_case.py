#!/usr/bin/env python3
"""Driving a shipped hook as its own process, for the gate-discharge suites.

Split out when `test_gate_discharge.py` reached the 450-line band floor. The
seam is the one `_observer_case.py` already uses: the DRIVER (how a real hook
process is run and its envelope read) is shared, while what each suite asserts
about the gates stays with that suite.

Extracted rather than band-ceilinged deliberately. `_pin_ceilings` retires an
entry when a split wins the ground back, on the stated grounds that a kept
entry hands that ground away — so taking a ceiling for a file that a split can
keep under the floor would be claiming room this does not need.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
from conftest import _PLUGIN_ROOT, _IntegrationTestCase

# The shapes the second harness's trigger actually takes. Not the whole
# `_READ_COMMANDS` set — the point is that the gate survives a read, and one
# pager plus one head is enough to show the property is not `cat`-specific.
_READ_COMMANDS = ("cat", "head", "less")


class _RealHookTestCase(_IntegrationTestCase):
    """Drive a shipped hook as its own process, against the shipped plugin."""

    def _run_hook(self, script: str, payload: dict) -> subprocess.CompletedProcess:
        """Through the shared driver, not a sixth hand-rolled `subprocess.run`.

        `CLAUDE_PLUGIN_ROOT` is the one override these cases need: the preloads
        the hooks below shell out to resolve their shared library through it.
        """
        return self._run_script_with_env(
            script, payload, {"CLAUDE_PLUGIN_ROOT": str(_PLUGIN_ROOT)}
        )

    def _skill_md(self, skill: str) -> Path:
        return _PLUGIN_ROOT / "skills" / skill / "SKILL.md"

    def _injected_context(self, result: subprocess.CompletedProcess) -> str:
        """The additionalContext the handler emitted, or "" when it emitted none.

        Read out of the real envelope rather than off raw stdout so a handler
        that printed the preload's output without the `hookSpecificOutput`
        wrapper — which reaches no model — cannot read as delivery.
        """
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return ""
        payload = json.loads(result.stdout)
        return payload.get("hookSpecificOutput", {}).get("additionalContext", "")

    def _arm_plan_gate(self) -> Path:
        """Arm the plan gate at a plan file that EXISTS, and return the marker.

        The existing file is load-bearing. Pointed at a missing one the
        review-plan preload takes its misfire branch, which clears the marker as
        garbage collection and returns early — so a fixture without a plan file
        would pass a "the gate survived" test against code that spends it.
        """
        plan = self.tmpdir / "plan.md"
        plan.write_text("# story-001 A plan\n\nStep 1.\n", encoding="utf-8")
        markers.marker_write(self.smm_dir, markers.PLAN_AWAITING_REVIEW, str(plan))
        return markers.marker_path(self.smm_dir, markers.PLAN_AWAITING_REVIEW)

    def _read_skill_body(self, skill: str, command: str = "cat") -> str:
        """Inject for a shell READ of `skill`'s body, and return what it injected.

        The claim is released first. On this leg the handler takes one claim per
        (session, skill) to collapse the burst of reads a single invocation
        produces, and the suite pins ONE session id — so a second drive in the
        same test would measure the claim, not the preload, and report "nothing
        injected" for a reason that has nothing to do with the gate. The shipped
        release is a 10s TTL, which a test must not sleep through.
        """
        for claim in self.smm_dir.glob(".preload-claim-*"):
            claim.unlink()
        result = self._run_hook(
            "preload_injection.py",
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"{command} {self._skill_md(skill)}"},
                "cwd": str(self.tmpdir),
                "session_id": "gate-discharge",
            },
        )
        return self._injected_context(result)
