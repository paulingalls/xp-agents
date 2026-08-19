#!/usr/bin/env python3
"""Reading a skill's body must spend none of its gates.

On the second harness there is no skill tool call: the model reads `SKILL.md`
with a shell command, and that read IS the invocation the injection handler
acts on (`preload_injection._READ_COMMANDS`). So the handler cannot tell a
plain `cat` of a skill body from a real invocation — and two preloads used to
spend a live gate merely by running, which made `cat` enough to disarm the
lead's plan-review and assign gates.

The fix is not detection. It is to discharge each gate at the act that
satisfies it, so the preload mutates nothing gate-related and the
read-vs-invocation question never has to be answered.

Every measurement here drives a REAL hook process over the REAL shipped
plugin root, not a predicate and not a fake preload: the property is "the gate
survived a run of the actual preload", and a stub preload would prove nothing
about the script that ships. Each read case therefore asserts BOTH halves —
state was injected (so the preload really ran) AND the gate survived. The
first half is what keeps the second from passing vacuously: a handler that
declined to run anything at all would satisfy "the gate survived" forever.
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import lead_gates
import markers
from _lead_gate_fixtures import BRANCH_001, _AssignGateTestCase
from conftest import _PLUGIN_ROOT, _IntegrationTestCase, _s, _sprint_json

# The shapes the second harness's trigger actually takes. Not the whole
# `_READ_COMMANDS` set — the point is that the gate survives a read, and one
# pager plus one head is enough to show the property is not `cat`-specific.
_READ_COMMANDS = ("cat", "head", "less")


class _RealHookTestCase(_IntegrationTestCase):
    """Drive a shipped hook as its own process, against the shipped plugin."""

    def _run_hook(self, script: str, payload: dict) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(_PLUGIN_ROOT / "scripts" / script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._env_with_plugin_root(),
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


class TestReadingTheAssignBodySpendsNoAssignGate(_RealHookTestCase):
    """The assign gate: `cat xp-assign/SKILL.md` used to consume ASSIGN_PENDING.

    The preload's own `--consume-gate` opt-in was the earlier defence, and it
    cannot hold here: the injected argv passes the flag, so the hook-side run a
    read triggers IS the opting-in caller. The gate has no discharging act in
    the preload at all now — nothing arms or spends it there.
    """

    def _arm(self) -> Path:
        markers.marker_write(
            self.smm_dir, markers.ASSIGN_PENDING, "sprint-001 story-001"
        )
        return markers.marker_path(self.smm_dir, markers.ASSIGN_PENDING)

    def test_a_read_injects_state_and_leaves_the_assign_gate_armed(self):
        for command in _READ_COMMANDS:
            with self.subTest(command=command):
                gate = self._arm()
                context = self._read_skill_body("xp-assign", command)
                self.assertIn(
                    "SMM_DIR=",
                    context,
                    "the real assign preload did not run, so the gate surviving "
                    "measures nothing",
                )
                self.assertTrue(
                    gate.is_file(),
                    f"a `{command}` of the assign body spent the lead's assign gate",
                )


class TestTheAssignMarkerStaysArmedButInert(_AssignGateTestCase):
    """The contract dropping `--consume-gate` rests on, pinned as a sequence.

    Nothing consumes ASSIGN_PENDING at assign time any more, so the marker now
    outlives the act it demanded. That is only safe because the gate is
    state-derived: `_unspawned_teammate_story_exists` is its `active_when`, and
    `lead_gates`'s own prose says it "goes false the moment the last teammate is
    spawned, and stays false through accept and close."

    A quote is not a test. The existing suite pins the spawned case and the
    already-done case as separate scenarios; what this adds is the LIFECYCLE —
    one story walked from un-spawned through accept and close, with the
    predicate read at each step. The step that matters is the last two: the
    worktree is gone by then, so a predicate keying on the worktree alone would
    read the story as un-spawned again and re-block the lead forever with a
    marker no act can now clear.
    """

    def _sprint_at(self, status: str) -> None:
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "As a user I can log in",
                        status,
                        execution_mode="teammate",
                        branch_name=BRANCH_001,
                    )
                ]
            )
        )

    def _predicate(self) -> bool:
        """The gate's `active_when`, read directly.

        `cwd` only reaches the worktree lookup, which `_spawned` patches, so the
        fixtures' own placeholder is the honest value here.
        """
        return lead_gates._unspawned_teammate_story_exists(
            {"cwd": "/tmp"}, self.smm_dir
        )

    def test_it_goes_false_at_the_spawn_and_stays_false_through_close(self):
        self._arm()

        self._sprint_at("in-progress")
        with self._spawned():
            self.assertTrue(
                self._predicate(),
                "an un-spawned promoted story has something to assign",
            )
        with self._spawned("story-001"):
            self.assertFalse(
                self._predicate(),
                "the last teammate is spawned — nothing left to assign",
            )

        # Accept and close: the story leaves in-progress and the worktree is
        # torn down, so `_spawned()` reports none live from here on.
        for status in ("reviewing", "closing", "done"):
            with self.subTest(status=status):
                self._sprint_at(status)
                with self._spawned():
                    self.assertFalse(
                        self._predicate(),
                        f"the marker revived at status={status} — the lead is now "
                        "write-gated by a gate no act can clear",
                    )


if __name__ == "__main__":
    import unittest

    unittest.main()
