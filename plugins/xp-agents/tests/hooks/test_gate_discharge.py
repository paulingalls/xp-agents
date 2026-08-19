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


class TestReadingTheReviewPlanBodySpendsNoPlanGate(_RealHookTestCase):
    """The plan gate: `cat xp-review-plan/SKILL.md` used to delete its marker.

    The preload cleared `.plan-awaiting-review` as its last act, i.e. at review
    START, which made this worse than a read problem: opening /xp-review-plan and
    aborting left the lead un-gated with no review having happened. The discharge
    moved to the plan reviewer's own completion, so neither a read nor an
    abandoned run can spend it.
    """

    def test_a_read_injects_the_plan_and_leaves_the_plan_gate_armed(self):
        for command in _READ_COMMANDS:
            with self.subTest(command=command):
                gate = self._arm_plan_gate()
                context = self._read_skill_body("xp-review-plan", command)
                self.assertIn(
                    "PLAN_FILE=",
                    context,
                    "the preload did not reach its own end — a misfire exit "
                    "would leave the gate assertion below measuring nothing",
                )
                self.assertTrue(
                    gate.is_file(),
                    f"a `{command}` of the review-plan body spent the plan gate",
                )


class TestTheReviewPlanRunIsNotBlockedByItsOwnGate(_RealHookTestCase):
    """Moving a discharge to the satisfying act risks self-block, so measure it.

    A gate the discharging skill cannot get past is worse than a gate that leaks:
    the leak costs one un-reviewed plan, the self-block costs every future one,
    with no recovery except deleting a marker by hand. That failure is what killed
    story-019's first design, so this walks the hooks a real /xp-review-plan run
    passes through with the marker armed and asserts none of them refuses it —
    rather than reasoning from where `check_lead_gates` is called.

    Not asserted here, because it is the gate WORKING and not a self-block: a
    lead writing non-plan code while a plan awaits review is still blocked. The
    plan gate is plan-files-exempt precisely so the planning loop stays open.
    """

    def _refusal(self, result: subprocess.CompletedProcess) -> str:
        """The block reason this hook process emitted, or "" if it allowed the call.

        Both shapes a PreToolUse hook can refuse with are checked: the JSON
        `{"decision": "block"}` envelope on stdout, and a bare exit 2 with the
        reason on stderr. A test that read only the first would call an exit-2
        refusal an allow.
        """
        if result.returncode != 0:
            return result.stderr.strip() or f"exit {result.returncode}"
        if not result.stdout.strip():
            return ""
        payload = json.loads(result.stdout)
        if payload.get("decision") == "block":
            return payload.get("reason", "blocked")
        return ""

    def _skill_payload(self) -> dict:
        return {
            "tool_name": "Skill",
            "tool_input": {"skill": "xp-agents:xp-review-plan"},
            "cwd": str(self.tmpdir),
            "session_id": "gate-discharge",
        }

    def test_the_refusal_probe_sees_a_refusal_that_really_happens(self):
        """The control for the three legs below, which all assert an ABSENCE.

        `_refusal` returning "" for every input imaginable would make each of
        them pass forever. So drive the same hook into a refusal it really ships:
        a CLI teammate invoking a lead-owned skill, from a cwd carrying the
        teammate path segment `identity.is_worktree_teammate` reads.
        """
        teammate_cwd = self.tmpdir / "worktree-story-001"
        teammate_cwd.mkdir()
        payload = {**self._skill_payload(), "cwd": str(teammate_cwd)}
        refusal = self._refusal(self._run_hook("pre_tool_skill.py", payload))
        self.assertNotEqual(refusal, "", "the refusal probe cannot see a refusal")

    def test_the_skill_call_is_allowed_while_its_own_gate_is_armed(self):
        self._arm_plan_gate()
        refusal = self._refusal(
            self._run_hook("pre_tool_skill.py", self._skill_payload())
        )
        self.assertEqual(refusal, "", "/xp-review-plan was refused by its own gate")

    def test_its_state_is_still_injected_while_its_own_gate_is_armed(self):
        """The other half of "not blocked": a skill allowed to run but starved of
        its state runs blind, which on the second harness is indistinguishable
        from working. The armed marker is what the preload reads the plan FROM."""
        self._arm_plan_gate()
        result = self._run_hook("preload_injection.py", self._skill_payload())
        self.assertIn("PLAN_FILE=", self._injected_context(result))

    def test_the_reviewer_subagent_starts_while_the_gate_is_armed(self):
        """The skill spawns `xp-plan-reviewer` with the Agent tool, so the run
        crosses one more hook before the discharge can happen."""
        self._arm_plan_gate()
        refusal = self._refusal(
            self._run_hook(
                "subagent_start.py",
                {
                    "session_id": "gate-discharge",
                    "agent_id": "review-1",
                    "agent_type": "xp-plan-reviewer",
                    "cwd": str(self.tmpdir),
                },
            )
        )
        self.assertEqual(refusal, "", "the plan reviewer could not be spawned")


class TestACompletedPlanReviewDischargesTheGate(_RealHookTestCase):
    """The allowed direction. Without this the story reads as a blunt disable.

    Driven through the real `subagent_stop.py` process, since that is where the
    discharge now lives and the whole point is that it happens at the reviewer's
    completion rather than at the preload's start.
    """

    def _reviewer_stopped(self) -> subprocess.CompletedProcess:
        return self._run_hook(
            "subagent_stop.py",
            {
                "session_id": "gate-discharge",
                "agent_id": "review-1",
                "agent_type": "xp-plan-reviewer",
                "last_assistant_message": "Review complete",
                "cwd": str(self.tmpdir),
            },
        )

    def _plan_reviewed_events(self) -> list[dict]:
        return [
            event
            for event in self._read_events()
            if event.get("metadata", {}).get("action") == "plan_reviewed"
        ]

    def test_the_reviewers_completion_clears_the_gate(self):
        gate = self._arm_plan_gate()
        result = self._reviewer_stopped()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            gate.exists(),
            "a completed plan review left the gate armed — the lead cannot write",
        )

    def test_the_evidence_is_written_before_the_marker_is_consumed(self):
        """Emit FIRST, consume SECOND, the rule its sibling close handler states:
        a crash between the two must leave evidence, not a silently consumed
        marker. Observable after the fact as "the discharge never happens without
        the record" — a consumed marker with no plan_reviewed event is the
        ordering this asserts against.
        """
        gate = self._arm_plan_gate()
        self._reviewer_stopped()
        self.assertEqual(len(self._plan_reviewed_events()), 1)
        self.assertFalse(gate.exists())

    def test_another_subagent_finishing_does_not_clear_it(self):
        """The discharge is the plan reviewer's completion, not any completion."""
        gate = self._arm_plan_gate()
        result = self._run_hook(
            "subagent_stop.py",
            {
                "session_id": "gate-discharge",
                "agent_id": "retro-1",
                "agent_type": "xp-retrospective",
                "last_assistant_message": "Retro complete",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(gate.exists(), "an unrelated subagent spent the plan gate")
        self.assertEqual(self._plan_reviewed_events(), [])


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
