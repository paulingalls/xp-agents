#!/usr/bin/env python3
"""E2E for the incremental two-teammate accept flow (M-3 capstone).

Built incrementally — this commit pins Phase 1+2 (mechanical-promote
state + .accept-suppression while reviewing). Subsequent commits will
add Phase 3 (xp-accept reviewing-first dispatch), Phase 5 (xp-story-
close + merge for A), Phase 6+7 (B identical flow + final state),
and a separate test_merge_failure_leaves_reviewing.

Composition pin — turns red only when a future change breaks the
M-3 contract across pieces (mechanical promote, reviewing-first
preload dispatch, close-then-done ordering, has_reviewing_stories
suppression of .accept re-arm, source-branch survives merge failure).
"""

import unittest

import markers
import pre_tool_write
import sprint_state
import sprint_store
from _branching_fixtures import create_teammate_worktree_with_commit
from conftest import (
    _IntegrationTestCase,
    _make_write_input,
    _s,
    _sprint_json,
)


class TestIncrementalTeammateAccept(_IntegrationTestCase):
    def test_two_teammate_incremental_flow(self):
        # Phase 1: setup — sprint with two stories both `in-progress`,
        # each with a real teammate worktree + commit. Mirrors the
        # state right after /xp-assign in teammate mode and both
        # teammates have begun work.
        sprint = _sprint_json(
            [
                _s("story-001", "Teammate A story", "in-progress"),
                _s("story-002", "Teammate B story", "in-progress"),
            ],
            sprint_id="sprint-test",
            started="2026-05-07",
        )
        (self.smm_dir / "sprint.json").write_text(sprint)
        env = self._test_env.copy()
        create_teammate_worktree_with_commit(str(self.tmpdir), "story-001", env)
        create_teammate_worktree_with_commit(str(self.tmpdir), "story-002", env)

        # Phase 2: teammate A exits rc=0 → spawn_teammate.py mechanical-
        # promote fires (the unit pin in test_spawn_teammate.py covers
        # the mechanism; capstone simulates the resulting state via
        # sprint_store directly to keep this composition-focused).
        sprint_store.update_story_status(self.smm_dir, "story-001", "reviewing")

        # AC1: A=reviewing, B=in-progress; predicates reflect both.
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-001")["status"],
            "reviewing",
            "A must self-promote to reviewing on clean exit",
        )
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-002")["status"],
            "in-progress",
            "B must remain in-progress while A is being accepted",
        )
        self.assertTrue(
            sprint_state.has_reviewing_stories(self.smm_dir),
            "has_reviewing_stories must reflect A",
        )
        self.assertTrue(
            sprint_state.has_in_progress_stories(self.smm_dir),
            "has_in_progress_stories must still reflect B",
        )
        # AC3: actually FIRE pre_tool_write — without invoking it the
        # assertFalse below proves nothing (the marker is only ever
        # written by pre_tool_write). With A reviewing AND B in-
        # progress, has_reviewing_stories suppresses re-arm, so .accept
        # MUST stay absent. This is the structural protection that
        # ACCEPT_ACTIVE used to provide pre-story-004.
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.ACCEPT))
        pre_tool_write.run(_make_write_input(), smm_dir=self.smm_dir)
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.ACCEPT),
            ".accept must not arm while a story is in reviewing",
        )


if __name__ == "__main__":
    unittest.main()
