#!/usr/bin/env python3
"""The start-time file_domain gate asks an ABSOLUTE question, not a delta.

Split from `test_file_domain_lock_lifecycle.py`, which pins the claim rule
itself and the gate's happy paths; this module pins the two ways the first
implementation got the QUESTION wrong.

1. It asked `introduced_collisions` whether this transition GREW the colliding
   set versus the on-disk baseline. A story parked back after promotion still
   holds its claim (its branch was cut), so the collision was already in the
   baseline, the set did not grow, and the promotion sailed through onto a
   running story's file — the exact pair the gate exists to stop. Whether a
   live collision pre-existed is no licence to add a second teammate to it.

2. `edit_story` relaxed the claim rule unconditionally, dropping the
   authoring-time leg: with every claimant parked, nothing held and two parked
   stories could grow onto one path through edit-story, surfacing much later as
   a refused promotion.

Both refusals are only useful with a way OUT, so the release path
(`update-story-branch <id> ''`) is pinned here too.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import sprint_store
from conftest import _s, _SMMTestCase

_SHARED = "src/shared.py"


def _sprint(stories):
    return {
        "sprint_id": "sprint-001",
        "goal": "t",
        "started": "2026-04-01",
        "milestone": "",
        "stories": stories,
    }


def _story(sid, status, path=_SHARED, **extra):
    story = _s(sid, sid, status)
    story["file_domain"] = [f"{path} — {sid}"]
    story.update(extra)
    return story


class TestStartTimeGateIsAbsoluteNotIncremental(_SMMTestCase):
    """The gate asks whether the STARTED story shares a live path once the
    transition lands — not whether this transition GREW the colliding set.

    A "did it grow" reading is fail-open for the case the gate exists for: a
    story parked back after promotion still holds its claim (its branch was
    cut), so the collision is already in the on-disk baseline, the set does not
    grow, and the promotion sails through onto a running story's file.
    """

    def _live_sharer_plus_parked_branched(self):
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "in-progress"),
                    _story("story-002", "scheduled", branch_name="wip/story-002"),
                ]
            ),
        )

    def test_promoting_a_parked_branched_sharer_is_refused(self):
        """REGRESSION. Both stories already hold the claim on disk, so the
        colliding set is identical before and after — and the promotion still
        puts two teammates on one file."""
        self._live_sharer_plus_parked_branched()
        with self.assertRaises(ValueError) as ctx:
            sprint_store.update_story_status(self.smm_dir, "story-002", "in-progress")
        msg = str(ctx.exception)
        self.assertIn(_SHARED, msg)
        self.assertIn("story-002", msg)
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-002")["status"], "scheduled"
        )

    def test_the_refusal_names_the_branch_release_remedy(self):
        """A stale claim's remedy is not 'fix the file_domain' — the claimant
        is parked and its domain is correct. The message must name the release."""
        self._live_sharer_plus_parked_branched()
        with self.assertRaises(ValueError) as ctx:
            sprint_store.update_story_status(self.smm_dir, "story-002", "in-progress")
        self.assertIn("update-story-branch", str(ctx.exception))

    def test_clearing_the_stale_branch_releases_the_claim(self):
        """The remedy works: `''` clears branch_name back to null, the parked
        story stops reserving the path, and the promotion is allowed."""
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "scheduled", branch_name="wip/story-001"),
                    _story("story-002", "scheduled"),
                ]
            ),
        )
        sprint_store.set_story_branch(self.smm_dir, "story-001", "")
        self.assertIsNone(
            sprint_store.get_story(self.smm_dir, "story-001")["branch_name"]
        )
        sprint_store.update_story_status(self.smm_dir, "story-002", "in-progress")
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-002")["status"], "in-progress"
        )

    def test_a_live_collision_between_others_does_not_block_this_start(self):
        """PIN on the scoping. The gate is absolute about the STARTED story's
        own paths only; a collision it can neither cause nor cure must not
        strand an unrelated story."""
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "in-progress"),
                    _story("story-002", "in-progress"),
                    _story("story-003", "scheduled", path="src/own.py"),
                ]
            ),
        )
        sprint_store.update_story_status(self.smm_dir, "story-003", "in-progress")
        self.assertEqual(
            sprint_store.get_story(self.smm_dir, "story-003")["status"], "in-progress"
        )

    def test_missing_smm_dir_raises_the_documented_valueerror(self):
        """Both writers document ValueError for a missing sprint. The lock file
        lives INSIDE smm_dir, so acquiring before loading turned that into a
        raw FileNotFoundError traceback."""
        missing = self.smm_dir / "nope"
        with self.assertRaises(ValueError):
            sprint_store.update_story_status(missing, "story-001", "in-progress")


class TestEditStoryStrictWhenTheEditedStoryIsParked(_SMMTestCase):
    """`running_only` is the LIVE story's relaxation, so it is keyed on the
    story being edited. Amending a parked story is authoring, not amendment."""

    def test_parked_story_may_not_grow_onto_another_parked_claim(self):
        """REGRESSION. A blanket running_only=True dropped the authoring-time
        leg: with every claimant parked, nothing held and the overlap landed."""
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "scheduled", "src/a.py"),
                    _story("story-002", "scheduled", _SHARED),
                ]
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            sprint_store.edit_story(
                self.smm_dir,
                "story-001",
                {"file_domain": ["src/a.py — a", f"{_SHARED} — amended"]},
            )
        self.assertIn(_SHARED, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
