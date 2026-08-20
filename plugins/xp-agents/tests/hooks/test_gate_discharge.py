#!/usr/bin/env python3
"""Who discharges the PLAN gate, and who must not be blocked by it.

The assign gate's half of this question moved to `test_assign_gate_discharge.py`
when the two together crossed the 500-line cap — the seam is the gate, because
the two clear by completely different mechanisms: the plan gate has no
`active_when` and is cleared only by the act it demands, while the assign gate is
state-derived. Anything shared by both lives in `_gate_discharge_case.py`.

Reading a skill's body must spend neither of them.

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
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import markers
import subagent_stop
from _gate_discharge_case import _READ_COMMANDS, _RealHookTestCase


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


class TestAMarkerHoldingNoPathIsCollected(_RealHookTestCase):
    """The shape the plugin actually arms on one of its two paths — and the one
    story-021 left with no exit at all.

    `_arm_plan_gate` points at a plan file that EXISTS. That is the shape
    `post_tool_exit_plan` arms when ExitPlanMode hands over a `filePath`, and it
    is not the only one shipped: `subagent_stop`'s Plan-via-Agent-tool leg has no
    plan path in its payload, so it writes the AGENT ID, and the same fallback
    catches an ExitPlanMode that supplies none. The marker then holds a non-path,
    `[ ! -f "$PLAN_PATH" ]` is always true, and the preload took a branch that
    neither consumed nor permitted a review: SKILL.md says stop without spawning
    the reviewer, and the reviewer's completion is the gate's only discharge. So
    the armed state had no exit, and re-entering plan mode through the same leg
    re-armed the same payload.

    THE ACT THAT DISCHARGES IT IS RUNNING /xp-review-plan (AC2). It collects,
    like the sibling arm where the marker names a deleted plan, and for the same
    reason: a gate no review can clear is garbage, and garbage is collected
    rather than left blocking. story-021 refused to consume here because a plain
    `cat` of the skill body would spend it — an objection that holds only while
    the gate is SATISFIABLE, which this one is not.

    Deliberately NOT the alternative the customer rejected: falling back to
    `.last-plan-path`. That file is written in exactly one place, the success
    tail of this same preload, so it always names the PREVIOUSLY reviewed plan —
    reviewing it would let a completed review of plan A discharge the gate armed
    for plan B, silently. See the plan's rationale; do not re-propose it.
    """

    def _arm_with_agent_id(self) -> Path:
        """Arm through the REAL writer, so the payload is the shipped one.

        `subagent_stop.run` on a finished `Plan` agent is what puts a non-path in
        this marker. Hand-writing "main" would prove the preload handles a string
        of that shape, not that it handles what the plugin arms.
        """
        result = self._run_hook(
            "subagent_stop.py",
            {
                "session_id": "gate-discharge",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "Plan ready",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        gate = markers.marker_path(self.smm_dir, markers.PLAN_AWAITING_REVIEW)
        self.assertTrue(gate.is_file(), "the real writer armed nothing")
        self.assertFalse(
            Path(gate.read_text().strip()).is_file(),
            "the fixture armed a real path — this case is about a NON-path",
        )
        return gate

    def test_running_the_skill_collects_a_non_path_marker(self):
        for command in _READ_COMMANDS:
            with self.subTest(command=command):
                gate = self._arm_with_agent_id()
                context = self._read_skill_body("xp-review-plan", command)
                self.assertIn(
                    "PLAN_FILE_ERROR=",
                    context,
                    "the preload emitted no diagnostic, so it did not reach the "
                    "non-path branch and the collect below measures nothing",
                )
                self.assertFalse(
                    gate.is_file(),
                    "a marker holding no plan path has no act that can satisfy "
                    "it, so it must be collected rather than left blocking",
                )

    def test_the_misfire_branch_still_collects_a_deleted_plan(self):
        """The sibling arm, unchanged — so the collapse is not a blunt widening.

        A marker naming a path that does not exist is unsatisfiable garbage and
        must still be collected, or a lead holding one is write-blocked with no
        act that can clear it.
        """
        markers.marker_write(
            self.smm_dir,
            markers.PLAN_AWAITING_REVIEW,
            str(self.tmpdir / "gone.md"),
        )
        gate = markers.marker_path(self.smm_dir, markers.PLAN_AWAITING_REVIEW)
        self._read_skill_body("xp-review-plan")
        self.assertFalse(
            gate.is_file(),
            "a marker naming a deleted plan must still be collected",
        )

    def test_both_collecting_arms_clear_the_last_reviewed_pointer(self):
        """`.last-plan-path` must go with the marker on BOTH arms.

        Left behind, the next invocation finds no marker, falls back to the
        pointer and silently re-emits the PREVIOUSLY reviewed plan instead of the
        loud "no plan marker" it owes the lead — the same reason the deleted-plan
        arm already cleared it, now that the non-path arm collects too.
        """
        pointer = self.smm_dir / ".last-plan-path"
        previous = self.tmpdir / "previously-reviewed.md"
        previous.write_text("# story-000 An earlier plan\n", encoding="utf-8")
        for payload, label in (
            (str(self.tmpdir / "gone.md"), "a path that names nothing"),
            ("plan-1", "no path at all"),
        ):
            with self.subTest(marker_holds=label):
                pointer.write_text(str(previous))
                markers.marker_write(
                    self.smm_dir, markers.PLAN_AWAITING_REVIEW, payload
                )
                self._read_skill_body("xp-review-plan")
                self.assertFalse(
                    pointer.exists(),
                    f"the marker held {label} and the stale pointer survived — "
                    "the next run resurrects the previously reviewed plan",
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

    def _reviewer_payload(self) -> dict:
        return {
            "session_id": "gate-discharge",
            "agent_id": "review-1",
            "agent_type": "xp-plan-reviewer",
            "last_assistant_message": "Review complete",
            "cwd": str(self.tmpdir),
        }

    def _reviewer_stopped(self) -> subprocess.CompletedProcess:
        return self._run_hook("subagent_stop.py", self._reviewer_payload())

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
        marker.

        Driven IN-PROCESS with a spy on the consume, because the ORDER is not
        visible in the outcome: "the event exists and the marker is gone" is true
        whichever way round those two lines run, so the assertion this class used
        to make stayed green when they were swapped — while in production a crash
        or a lock timeout between them left the gate discharged with no record at
        all. The spy reads the log as it stood AT the consume, which is exactly
        what such a crash would leave behind.
        """
        gate = self._arm_plan_gate()
        evidence_at_consume: list[int] = []
        real_consume = markers.marker_consume

        def spy(smm_dir, marker, *args, **kwargs):
            if marker is markers.PLAN_AWAITING_REVIEW:
                evidence_at_consume.append(len(self._plan_reviewed_events()))
            return real_consume(smm_dir, marker, *args, **kwargs)

        with patch.object(markers, "marker_consume", side_effect=spy):
            subagent_stop.run(self._reviewer_payload(), smm_dir=self.smm_dir)

        self.assertEqual(
            evidence_at_consume,
            [1],
            "the gate was discharged before its plan_reviewed record existed",
        )
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


if __name__ == "__main__":
    import unittest

    unittest.main()
