#!/usr/bin/env python3
"""The assign marker is scoped to the stories it was armed for.

Third split of the lead-gate suite (after test_write_gate_fails_closed.py), for
the same 500-line reason; the shared fixtures stay in tests/_lead_gate_fixtures.py.

WHY SCOPING, ON TOP OF THE STATE-DERIVED PREDICATE. `check_lead_gates` already
deletes a moot marker — but the delete needs a LEAD WRITE to fire, and the assign
gate is plan-files-exempt with the exemption checked BEFORE the marker, so the
whole plan-mode window skips the consume entirely. A marker that goes moot and
sees no non-plan lead write before the next delegated frontier is promoted fires
in that frontier's PRE-PLAN window. The damage is not a nag: running the assign
skill there does clear the marker, but its preload pairs the demand with the
PREVIOUS story's recorded plan path, so a teammate gets spawned on the wrong plan
and the branch-name check cannot see it.

Scoping closes it at the source: the marker records WHICH stories it was armed
for, and the predicate intersects against them, so an unrelated frontier is
never in scope.

CONTENT SHAPE, NOT CONTENT SNIFFING. Scoped-vs-legacy is decided by a fixed
sentinel prefix, never inferred:
  - "more than one token" makes a ONE-story armed set — the common frontier
    shape — read as legacy, so the fix would be inert exactly where it matters;
  - "contains a dash" flips the legacy `xp-plan-reviewer` payload to scoped;
  - "the tokens are ids in sprint.json" breaks across a sprint rollover, and
    story ids are unvalidated free strings, so `a` is a legal id.
The literal format is pinned HERE and again on the writer's side in
test_subagent_stop_handlers.py — deliberately by hand on both sides, so a change
to the codec cannot keep both green on its own.

EVERY NEW FAILURE MODE FAILS CLOSED. A False from the predicate DELETES the
marker, so anything the reader cannot trust — no sentinel, another sprint's id,
an empty set, an unreadable marker — falls back to the unscoped behavior and
stays armed.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import lead_gates
from _lead_gate_fixtures import BRANCH_001, BRANCH_002, _AssignGateTestCase, _lead_write
from conftest import _s, _sprint_json

SPRINT_ID = "sprint-042"


def _scoped(sprint_id: str, *story_ids: str) -> str:
    """The armed-scope payload, spelled out by hand — this is the contract."""
    return f"sprint={sprint_id};stories={','.join(story_ids)}"


def _sprint(stories, sprint_id: str = SPRINT_ID) -> str:
    return _sprint_json(stories, sprint_id=sprint_id)


def _teammate(story_id: str, branch: str, status: str = "in-progress") -> dict:
    return _s(
        story_id,
        f"Story {story_id}",
        status,
        execution_mode="teammate",
        branch_name=branch,
    )


class _ScopedAssignGateTestCase(_AssignGateTestCase):
    def _arm_scoped(self, sprint_json: str, *armed_ids: str) -> None:
        """Arm the marker for *armed_ids* only, then install the sprint."""
        self._arm(sprint_json)
        (self.smm_dir / ".assign-pending").write_text(_scoped(SPRINT_ID, *armed_ids))


class TestAssignMarkerIsScopedToItsStories(_ScopedAssignGateTestCase):
    def test_marker_for_a_finished_story_does_not_gate_a_new_frontier(self):
        """AC-1. The marker was armed for story-001's plan review; story-001 is
        done and the next delegated frontier (story-002) has just been promoted,
        pre-plan-review. Nothing about story-002 has been assigned yet, so the
        unscoped predicate says "something to assign" and the gate fires — in the
        exact window where the demand pairs story-002 with story-001's plan.
        """
        self._arm_scoped(
            _sprint(
                [
                    _s("story-001", "First", "done", execution_mode="teammate"),
                    _teammate("story-002", BRANCH_002),
                ]
            ),
            "story-001",
        )
        with self._spawned():  # story-002 un-spawned: unscoped predicate says BLOCK
            self._assert_allows(_lead_write())

    def test_a_moot_scoped_marker_is_consumed_not_merely_skipped(self):
        """Same distinction the unscoped gate draws: a skipped marker is still on
        disk and fires again the moment state satisfies the predicate."""
        self._arm_scoped(
            _sprint(
                [
                    _s("story-001", "First", "done", execution_mode="teammate"),
                    _teammate("story-002", BRANCH_002),
                ]
            ),
            "story-001",
        )
        with self._spawned():
            self._assert_allows(_lead_write())
        self.assertFalse((self.smm_dir / ".assign-pending").exists())

    def test_in_flight_armed_story_still_gates(self):
        """AC-2. The story the marker was armed for is still promoted and
        un-spawned — the assignment it demands is real. Unchanged from today."""
        self._arm_scoped(_sprint([_teammate("story-001", BRANCH_001)]), "story-001")
        with self._spawned():
            self._assert_blocks(_lead_write())

    def test_an_armed_story_among_out_of_scope_ones_still_gates(self):
        """The intersection narrows the candidates; it must not empty them. Only
        story-001 is in scope and it is un-spawned, so the gate holds even though
        story-002 — out of scope — is already spawned."""
        self._arm_scoped(
            _sprint(
                [
                    _teammate("story-001", BRANCH_001),
                    _teammate("story-002", BRANCH_002),
                ]
            ),
            "story-001",
        )
        with self._spawned("story-002"):
            self._assert_blocks(_lead_write())

    def test_scope_does_not_revive_a_spawned_story(self):
        """Scoping only ever REMOVES candidates. An in-scope story that already
        has its teammate is still nothing to assign."""
        self._arm_scoped(_sprint([_teammate("story-001", BRANCH_001)]), "story-001")
        with self._spawned("story-001"):
            self._assert_allows(_lead_write())


class TestUntrustworthyScopeFallsBackToLegacy(_ScopedAssignGateTestCase):
    """AC-3. Anything the reader cannot trust degrades to the unscoped predicate
    — which stays armed — rather than crashing or silently opening the gate."""

    def _arm_raw(self, content: str) -> None:
        self._arm(_sprint([_teammate("story-001", BRANCH_001)]))
        (self.smm_dir / ".assign-pending").write_text(content)

    def test_legacy_agent_id_payload_blocks_as_before(self):
        """A marker written before scoping existed holds the reviewer's agent id.
        `_arm`'s own content is that payload — the legacy-compat pin."""
        self._arm(_sprint([_teammate("story-001", BRANCH_001)]))
        with self._spawned():
            self._assert_blocks(_lead_write())

    def test_legacy_agent_id_payload_is_still_consumed_when_moot(self):
        """The other half: legacy means TODAY's behavior in both directions, so a
        legacy marker whose state moved on must still be deleted."""
        self._arm(_sprint([_s("story-001", "First", "done")]))
        with self._spawned():
            self._assert_allows(_lead_write())
        self.assertFalse((self.smm_dir / ".assign-pending").exists())

    def test_another_sprints_scope_blocks(self):
        """Story ids repeat every sprint and nothing sweeps this marker at a
        sprint boundary, so a bare id would match a DIFFERENT story-001 this
        sprint. The recorded sprint id is what makes the ids mean something; a
        mismatch is 'cannot tell', which must stay armed."""
        self._arm_raw(_scoped("sprint-041", "story-001"))
        with self._spawned():
            self._assert_blocks(_lead_write())

    def test_a_sprint_with_no_id_never_matches_a_scope(self):
        """The other half of the sprint-id rule, and the one an equality check
        alone gets wrong: an EMPTY id identifies no sprint, so a scope armed
        under one must not match it back. `sprint_id` is only schema-required to
        be a string, and `sprint_schema.empty_sprint` seeds it "" — so `"" ==
        ""` would make every id-less sprint the same sprint, which is exactly
        the rollover confusion the recorded id exists to stop. Unknown stays
        armed.
        """
        self._arm(_sprint([_teammate("story-001", BRANCH_001)], sprint_id=""))
        (self.smm_dir / ".assign-pending").write_text(_scoped("", "story-999"))
        with self._spawned():
            self._assert_blocks(_lead_write())

    def test_empty_recorded_set_blocks(self):
        """An empty set read as 'nothing armed' would delete a marker the lead
        still needs. It means the writer told us nothing, not that there is
        nothing to do."""
        self._arm_raw(_scoped(SPRINT_ID))
        with self._spawned():
            self._assert_blocks(_lead_write())

    def test_unreadable_marker_leaves_the_predicate_armed(self):
        """Asserted on the predicate, not through the gate: `marker_exists`
        already rejects an unreadable marker and skips the gate before the
        predicate runs. The branch is still reachable — the marker can vanish
        between that stat and this read — and `marker_read` returns None for
        every such case (missing, symlink, OSError), so the fallback needs no
        new exception handling. What it does need is to be the ARMED fallback.
        """
        self._arm(_sprint([_teammate("story-001", BRANCH_001)]))
        (self.smm_dir / ".assign-pending").unlink()
        with self._spawned():
            self.assertTrue(
                lead_gates._unspawned_teammate_story_exists(_lead_write(), self.smm_dir)
            )

    def test_corrupt_sprint_still_blocks_with_a_scoped_marker(self):
        """The fail-closed invariant the new read must not weaken: a sprint we
        cannot parse is 'could not tell', and the scope lookup must never turn
        that into a delete. The sprint read comes first and returns True."""
        self._arm(_sprint([_teammate("story-001", BRANCH_001)]))
        (self.smm_dir / ".assign-pending").write_text(_scoped(SPRINT_ID, "story-999"))
        (self.smm_dir / "sprint.json").write_text("{not json")
        with self._spawned():
            self._assert_blocks(_lead_write())


if __name__ == "__main__":
    unittest.main()
