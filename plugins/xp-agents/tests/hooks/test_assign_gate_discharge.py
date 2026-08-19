#!/usr/bin/env python3
"""Who discharges the ASSIGN gate, and who must not be blocked by it.

Split from `test_gate_discharge.py` at the 500-line cap. The seam is the gate:
that file keeps the PLAN gate (a read must not spend it, the reviewer's
completion must, and the review must not be blocked by its own gate); this one
owns the same three questions for `.assign-pending`. Both drive real hook
processes over the real shipped plugin root, through the shared
`_gate_discharge_case` / `_lead_gate_fixtures` drivers.

The assign gate is the harder of the two, because it is STATE-DERIVED: nothing
consumes `.assign-pending` at assign time, so the marker outlives the act it
demanded and `check_lead_gates` deletes it only when `active_when` says there is
nothing left to assign. Every question below is a question about that predicate:

  * a READ of the skill body must not spend it (the second harness has no skill
    tool call, so a `cat` of SKILL.md is what triggers the preload);
  * every no-spawn OUTCOME must make it go false — the leg story-021 left with
    no discharge at all;
  * the marker must stay inert but alive across the story lifecycle;
  * and the one write /xp-assign owes its own spawn must get past it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import _common
import lead_gates
import markers
import pre_tool_write
from _gate_discharge_case import _READ_COMMANDS, _RealHookTestCase
from _lead_gate_fixtures import (
    BRANCH_001,
    SPRINT_TEAMMATE_IN_PROGRESS,
    _AssignGateTestCase,
    _lead_write,
)
from conftest import _PLUGIN_ROOT, _s, _sprint_json, run_cli


def _write_to(path: str) -> dict:
    """A lead Write aimed at *path* — `_lead_write` defaults to a code file."""
    return _lead_write(tool_input={"file_path": path, "content": "x"})


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


class TestEveryNoSpawnOutcomeDischargesTheAssignGate(_AssignGateTestCase):
    """The three ways /xp-assign resolves a story WITHOUT spawning a teammate.

    Moving the discharge to the spawn left each of them with no discharge AT
    ALL. There is no `marker_consume(ASSIGN_PENDING)` anywhere in the plugin;
    the only clearer is `check_lead_gates` deleting the marker when `active_when`
    goes False, and that predicate reads worktree liveness — which stays
    "un-spawned" forever on an outcome that never spawns. The lead was then
    blocked from every non-plan Write, told to run /xp-assign, and running it
    changed nothing.

    Each outcome is asserted SEPARATELY. They fail independently: the in-agent
    one needs a recorded story field, teammates-off needs a config read, and
    all-spawned needs neither — one row covering "some no-spawn exit clears it"
    would go green on the outcome that already worked.

    Armed through the real writer, never by hand — see `_arm_via_plan_review`.
    """

    def _assert_discharged(self, *live: str) -> None:
        """Both halves: the write is allowed AND the marker is gone.

        The marker half is not redundant. A predicate that merely declines to
        fire leaves the marker on disk, and the next /xp-schedule promoting a
        teammate frontier springs the gate back — demanding /xp-assign for a
        story whose plan review has not happened yet. Self-clearing means
        DELETED; see `lead_gates._LeadGate.active_when`.
        """
        marker = markers.marker_path(self.smm_dir, markers.ASSIGN_PENDING)
        with self._spawned(*live):
            self._assert_allows(_lead_write())
        self.assertFalse(
            marker.is_file(),
            "the gate stopped firing but kept its marker — the next promoted "
            "frontier revives it with no plan review behind it",
        )

    def test_the_in_agent_outcome_discharges_it(self):
        """Branch 3 (and branch 2's forced variant): continue in the checkout.

        The one outcome of the execution-shape decision that used to persist
        NOTHING, so it was indistinguishable from "not assigned yet".
        """
        self._arm_via_plan_review(SPRINT_TEAMMATE_IN_PROGRESS)
        self._record_execution_mode("story-001", "in-agent")
        self._assert_discharged()

    def test_teammates_off_discharges_it(self):
        """Branch 1: the session has teammate support off, so no spawn is
        possible at all and the gate demands an impossible act."""
        self._arm_via_plan_review(SPRINT_TEAMMATE_IN_PROGRESS)
        markers.write_teammate_config(self.smm_dir, "off")
        self._assert_discharged()

    def test_the_all_spawned_outcome_discharges_it(self):
        """Pre-flight's "All teammates spawned" exit — the outcome that already
        worked, kept as the control: with it, a regression that broke only the
        two new legs cannot hide behind a green suite for this class."""
        self._arm_via_plan_review(SPRINT_TEAMMATE_IN_PROGRESS)
        self._assert_discharged("story-001")

    def test_a_live_batch_still_blocks(self):
        """The gate WORKING, so none of the above reads as a blunt disable: a
        promoted teammate story with no worktree still demands /xp-assign."""
        self._arm_via_plan_review(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._spawned():
            self._assert_blocks(_lead_write())


class TestTheAssignGateDoesNotBlockTheSpawnItDemands(_AssignGateTestCase):
    """/xp-assign Step 3 writes the teammate prompt the Step 4 spawn reads.

    At Step 3 the batch is promoted and no worktree exists yet, so the gate's
    predicate is True — and the prompt lives under /tmp, which the plan-file
    exemption never covered. The gate therefore blocked the act that satisfies
    it: the whole parallel pipeline stops, with no recovery but deleting a
    marker by hand.

    The path is resolved by `spawn_teammate --print-prompt-path`, the process
    /xp-assign itself queries — not spelled out here. A hand-written path is a
    guess about where the writer puts the file, and an exemption keyed on a
    guess drifts silently the moment the namespace changes.
    """

    def _prompt_path(self) -> str:
        result = run_cli(
            _PLUGIN_ROOT / "scripts" / "spawn_teammate.py",
            ["--print-prompt-path", "--name", "worktree-story-001"],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        path = result.stdout.strip()
        self.assertTrue(path, "--print-prompt-path printed nothing")
        return path

    def _assert_write_allowed(self, path: str) -> None:
        """Drive the real hook, because the exemption IS the hook's path math.

        `_assert_allows` calls `check_lead_gates` directly with the exemption
        hard-coded False — right for the gate's own suite, useless here: the
        question is whether `pre_tool_write` recognises the prompt path at all.
        """
        try:
            pre_tool_write.run(_write_to(path), smm_dir=self.smm_dir)
        except _common.BlockedError as e:  # pragma: no cover - failure path
            self.fail(f"the teammate prompt write was blocked: {e}")

    def test_the_prompt_write_is_not_blocked_while_the_gate_is_armed(self):
        self._arm_via_plan_review(SPRINT_TEAMMATE_IN_PROGRESS)
        prompt = self._prompt_path()
        with self._spawned():  # no worktree yet — exactly the Step 3 state
            self._assert_write_allowed(prompt)

    def test_the_exemption_does_not_open_the_rest_of_the_namespace(self):
        """Narrow, not "anything under /tmp": the prompt file is the only write
        /xp-assign owes the spawn. A blanket exemption would let the gate be
        walked around by choosing a directory."""
        self._arm_via_plan_review(SPRINT_TEAMMATE_IN_PROGRESS)
        sibling = str(Path(self._prompt_path()).parent / "notes.md")
        with self._spawned():
            self._assert_blocks(_write_to(sibling))

    def test_the_prompt_write_weakens_no_other_gate(self):
        """The plan-file flag ALSO suppresses the accept-marker re-arm, so
        widening it in place would have made a prompt write stop signalling
        "this sprint needs acceptance" — a second, unrelated gate quietly
        weakened by a fix aimed at this one. And the exemption must be a SKIP,
        never a discharge: the marker has to outlive it, or writing the prompt
        would spend a gate the spawn has not yet satisfied.
        """
        self._arm_via_plan_review(SPRINT_TEAMMATE_IN_PROGRESS)
        prompt = self._prompt_path()
        with self._spawned():
            self._assert_write_allowed(prompt)
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.ACCEPT),
            "the prompt write no longer signals that the sprint needs "
            "acceptance — the exemption leaked into the plan-file flag",
        )
        self.assertTrue(
            markers.marker_path(self.smm_dir, markers.ASSIGN_PENDING).is_file(),
            "the prompt write spent the assign gate — it is exempt from it, "
            "not a discharge for it",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
