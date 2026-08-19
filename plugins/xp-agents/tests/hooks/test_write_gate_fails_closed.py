#!/usr/bin/env python3
"""Every read the Write/Edit hot path makes must fail CLOSED.

Split from test_lead_gates.py and test_pre_tool_write_gates.py (both over the
500-line cap) along the seam the bug itself drew: the two modules are different,
the failure is one. A gate that cannot READ the state it gates on has exactly two
options, and only one of them is safe:

  * BLOCK — say so, and let the human fix the state. Recoverable.
  * ALLOW — wave the write through un-gated. Silent, and on a release that ships
    to every user, permanent.

Three reads reach this path, and all three used to take the second option:

  1. `git worktree list` fails            -> lead_gates._unspawned_teammate_story_exists
  2. sprint.json is corrupt/unreadable    -> the same predicate, AND pre_tool_write.run
  3. a STALE same-id worktree is present  -> lead_gates._story_is_spawned

(2) and (3) shipped in this sprint. Both fail open, and (3) is worse than a
skipped gate: `check_lead_gates` CONSUMES the marker on a False, so a misread
does not merely skip the gate once — it DELETES it, and nothing re-arms it.

The destructive consume is why these tests exist as a suite rather than as
scattered edge cases. Its whole licence is that a False can only ever mean "the
sprint positively says there is nothing to assign", never "could not tell".
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import lead_gates
import pre_tool_write
import worktree
from _lead_gate_fixtures import (
    SPRINT_TEAMMATE_IN_PROGRESS,
    _AssignGateTestCase,
    _lead_write,
)
from conftest import _HookTestCase, _make_write_input, _s, _sprint_json


class TestAssignGatePredicateFailsClosed(_AssignGateTestCase):
    """The consume is DESTRUCTIVE, so its licence is that False can only ever
    mean "the sprint positively says there is nothing to assign" — never "could
    not tell". A predicate that answered False on a bad read would delete its own
    arming marker and silently un-gate the lead.

    Part of that licence rests on a property of ANOTHER module: worktree's git
    call swallows a failure into an empty iterator. Nothing pinned it, so a future
    refactor of `_iter_live_teammate_worktrees` — raising instead of swallowing,
    or returning a sentinel — could turn this gate into a marker-eater with every
    test still green. These pin the seam itself, through the real worktree code,
    not through the patched batch lookup.
    """

    def _git_broken(self):
        """The real chain, with git failing — not the batch lookup patched out."""
        return patch.object(
            worktree.subprocess,
            "check_output",
            side_effect=OSError("git not on PATH"),
        )

    def test_a_failing_git_blocks_rather_than_reading_stories_as_spawned(self):
        """No worktrees discoverable -> every promoted story reads as un-spawned
        -> the gate holds. The inverse (unreadable == nothing to do) would let a
        broken git wave through the very assignment the marker is demanding."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._git_broken():
            self._assert_blocks(_lead_write())

    def test_a_failing_git_never_consumes_the_marker(self):
        """The destructive half. A bad read must leave the marker armed: consume
        it and the gate is gone for good, with nothing left to re-arm it."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._git_broken():
            self._assert_blocks(_lead_write())
        self.assertTrue(
            (self.smm_dir / ".assign-pending").exists(),
            "a predicate that cannot tell must not delete its own arming marker",
        )

    def test_a_corrupt_sprint_blocks_rather_than_crashing_the_hook(self):
        """The other bad read, and the one that used to fail OPEN.

        `load_sprint` RAISES on malformed JSON (SprintCorruptError, a ValueError)
        rather than returning None. Nothing caught it, so the hook died with a
        traceback and exited 1 — which PreToolUse treats as a NON-blocking error.
        The write went through. "The marker survived" was true and beside the
        point: the gate did not fire.

        A bad read must fail CLOSED. Note the assertion is on BlockedError, not
        merely on "some exception": only a BlockedError reaches PreToolUse as a
        block (exit 2).
        """
        self._arm("{ not json")
        with self.assertRaises(_common.BlockedError):
            pre_tool_write.run(_lead_write(), smm_dir=self.smm_dir)
        self.assertTrue(
            (self.smm_dir / ".assign-pending").exists(),
            "a corrupt sprint must not disarm the gate",
        )

    def test_a_corrupt_sprint_still_reaches_the_question_gate(self):
        """The assign gate is checked BEFORE the question gate, so a raise inside
        the assign predicate short-circuits the whole table — a blocking question
        goes silently un-gated because a DIFFERENT gate's read blew up. Failing
        closed keeps every gate reachable: something blocks, whichever fires."""
        self._arm("{ not json")
        (self.smm_dir / ".question-gate").write_text("q")
        with self.assertRaises(_common.BlockedError):
            lead_gates.check_lead_gates(
                _lead_write(), self.smm_dir, is_machinery_write=False
            )
        self.assertTrue((self.smm_dir / ".question-gate").exists())

    def test_a_corrupt_sprint_never_consumes_the_marker_via_the_predicate(self):
        """The destructive half, at the predicate seam. `active_when` returning
        False is a licence to DELETE the marker, so an unreadable sprint must
        never produce a False — 'could not tell' is not 'nothing to assign'.
        Asserts the predicate directly: a caller that merely happens to raise
        first would mask a predicate that answers False."""
        self._arm("{ not json")
        self.assertTrue(
            lead_gates._unspawned_teammate_story_exists(_lead_write(), self.smm_dir)
        )
        self.assertTrue((self.smm_dir / ".assign-pending").exists())

    def test_a_stale_same_id_worktree_does_not_read_as_spawned(self):
        """The cross-sprint story-id collision.

        sprint-116's story-001 leaves `.claude/worktrees/worktree-story-001`
        registered on ITS branch. sprint-117 promotes its own story-001. Matching
        on the story id ALONE reads the stale worktree as this story's live
        teammate — and because the consume fires on a False, the gate is not
        merely skipped but DELETED, with nothing left to re-arm it: /xp-assign is
        never demanded, no teammate is ever spawned, and the lead implements the
        story in the main checkout with its commits misattributed.

        This is the identical hazard `spawn_prompt.load_prompt_for_story` was
        added to defend against for the PROMPT file, and it is answered the same
        way — on the branch, which carries the slug that tells two sprints'
        story-001 apart.
        """
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._spawned(
            "story-001", branches={"story-001": "dev/story-001-last-sprints-slug"}
        ):
            self._assert_blocks(_lead_write())

    def test_a_stale_same_id_worktree_never_consumes_the_marker(self):
        """The destructive half of the collision. Skipping the gate is
        recoverable — the next Write re-evaluates. Eating the marker is not."""
        self._arm(SPRINT_TEAMMATE_IN_PROGRESS)
        with self._spawned(
            "story-001", branches={"story-001": "dev/story-001-last-sprints-slug"}
        ):
            self._assert_blocks(_lead_write())
        self.assertTrue(
            (self.smm_dir / ".assign-pending").exists(),
            "a stale cross-sprint worktree must not disarm the gate",
        )

    def test_a_story_with_no_branch_yet_can_never_read_as_spawned(self):
        """/xp-assign cuts the branch (Step 2) BEFORE it spawns (Step 4), so a
        story with no recorded branch has certainly not been spawned. A worktree
        on a detached HEAD reports an EMPTY branch too — and `"" == ""` would let
        those two nothings match, re-opening the id-only hole for exactly the
        states that are least trustworthy."""
        self._arm(
            _sprint_json(
                [
                    _s(
                        "story-001",
                        "As a user I can log in",
                        "in-progress",
                        execution_mode="teammate",
                    )  # no branch_name — pre-Step-2
                ]
            )
        )
        with self._spawned("story-001", branches={"story-001": ""}):
            self._assert_blocks(_lead_write())


class TestUnreadableSprintFailsClosed(_HookTestCase):
    """The same bad read, one gate further down: pre_tool_write.run's OWN sprint
    read, which the schedule gate and the accept marker sit behind.

    `sprint_store.load_sprint` RAISES on undecodable bytes, malformed JSON, a
    schema failure, or a symlink. run() called it bare, so the exception escaped
    as an uncaught traceback and the hook exited 1 — a NON-BLOCKING error to
    PreToolUse. Every gate downstream of that read was skipped and the write
    landed. A half-written sprint.json from a crashed CAS is enough to reach it.
    """

    def _code_write(self):
        return _make_write_input(session_id="t", cwd="/tmp")

    def test_corrupt_sprint_blocks_the_write(self):
        (self.smm_dir / "sprint.json").write_text("{ not json")
        with self.assertRaises(_common.BlockedError) as ctx:
            pre_tool_write.run(self._code_write(), smm_dir=self.smm_dir)
        self.assertIn("sprint.json", str(ctx.exception))

    def test_schema_invalid_sprint_blocks_the_write(self):
        """Schema-invalid is the same class of unreadable: `load_sprint` raises
        SprintCorruptError for it too, and a sprint whose stories cannot be
        parsed cannot answer whether a frontier needs scheduling."""
        (self.smm_dir / "sprint.json").write_text('{"stories": "not-a-list"}')
        with self.assertRaises(_common.BlockedError):
            pre_tool_write.run(self._code_write(), smm_dir=self.smm_dir)

    def test_smm_write_stays_exempt_so_the_sprint_can_be_repaired(self):
        """The recovery path, and the reason failing closed is not a trap.
        sprint.json lives IN the SMM dir, so a gate that blocked every write while
        the file was broken would block the only tool that can fix it. SMM writes
        are already exempt from the schedule gate; the corrupt case inherits that
        exemption.
        """
        (self.smm_dir / "sprint.json").write_text("{ not json")
        smm_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": str(self.smm_dir / "sprint.json"),
                "content": "{}",
            },
        )
        pre_tool_write.run(smm_input, smm_dir=self.smm_dir)  # must not raise

    def test_plan_file_stays_exempt(self):
        """Plan files are excluded before the sprint is read at all."""
        (self.smm_dir / "sprint.json").write_text("{ not json")
        plan_input = _make_write_input(
            session_id="t",
            cwd="/tmp",
            tool_input={
                "file_path": "/Users/x/.claude/plans/my-plan.md",
                "content": "# Plan",
            },
        )
        pre_tool_write.run(plan_input, smm_dir=self.smm_dir)  # must not raise


if __name__ == "__main__":
    unittest.main()
