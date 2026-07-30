#!/usr/bin/env python3
"""A file_domain claim is lifecycle-scoped: it constrains while the story runs.

`file_domain` exists to prove two stories can run CONCURRENTLY without
stepping on each other. The claim rule used to exempt only terminal statuses,
so a story that had never started — and might never start — still reserved a
file against every other story. These tests pin the narrower rule and, just as
importantly, pin that the concurrency guarantee did NOT weaken with it.

Two axes, and the pairing between them is the whole story:

- `running_only=False` (the default) is today's behaviour, unchanged. Authoring
  a sprint and asking "could this frontier fan out?" are both hypothetical
  questions about stories that have not run yet, so both keep the strict rule.
  Default-strict also means an omitted keyword fails CLOSED.
- `running_only=True` asks "is this claim live right now?" — the question
  `edit_story` and the start-time gate ask. A claim is live when its story is
  in motion, or when a branch was cut for it (work may exist even if the story
  was parked back).

A write-time relaxation alone leaves a staggered hole — two parked stories on
one path coexist, then get promoted one at a time, so no pair is ever on the
frontier together. Closing that is the start-time gate, pinned next.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import file_domain_lock
import sprint_save
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


class TestClaimHoldsWhileRunning(unittest.TestCase):
    """The pure rule, exercised through `collision_report` on both settings."""

    def _pair(self, a_extra, b_extra):
        return _sprint(
            [
                _story("story-001", **a_extra),
                _story("story-002", **b_extra),
            ]
        )

    def test_never_started_pair_does_not_collide_under_running_only(self):
        """NEW BEHAVIOUR. Two stories that have never started share a path.
        Neither has run, so neither reserves it."""
        data = self._pair({"status": "ready"}, {"status": "scheduled"})
        self.assertEqual(file_domain_lock.collision_report(data, running_only=True), {})

    def test_same_pair_still_collides_on_the_strict_default(self):
        """The default reproduces today's behaviour exactly — an omitted
        keyword must fail closed, not open."""
        data = self._pair({"status": "ready"}, {"status": "scheduled"})
        report = file_domain_lock.collision_report(data)
        self.assertEqual(
            sorted(c["story_id"] for c in report[_SHARED]),
            ["story-001", "story-002"],
        )

    def test_branched_scheduled_story_still_holds_its_claim(self):
        """NEW BEHAVIOUR. `scheduled` alone does not mean never-started: a
        story CAN be parked back after promotion, and its branch may already
        carry commits. `branch_name` is the never-started discriminator."""
        data = self._pair(
            {"status": "in-progress"},
            {"status": "scheduled", "branch_name": "wip/story-002"},
        )
        report = file_domain_lock.collision_report(data, running_only=True)
        self.assertEqual(
            sorted(c["story_id"] for c in report[_SHARED]),
            ["story-001", "story-002"],
        )

    def test_empty_branch_name_reads_as_never_branched(self):
        """`""` is how the store spells "no branch" (see
        get_story_branch_name), so it must not count as a cut branch."""
        data = self._pair(
            {"status": "in-progress"},
            {"status": "scheduled", "branch_name": ""},
        )
        self.assertEqual(file_domain_lock.collision_report(data, running_only=True), {})

    def test_two_running_stories_still_collide_under_running_only(self):
        """PRESERVATION PIN. The concurrency guarantee: two stories with no
        dependency edge, both live, both claiming one path -> still refused."""
        data = self._pair({"status": "in-progress"}, {"status": "reviewing"})
        report = file_domain_lock.collision_report(data, running_only=True)
        self.assertEqual(
            sorted(c["story_id"] for c in report[_SHARED]),
            ["story-001", "story-002"],
        )

    def test_running_pair_with_dependency_edge_is_not_a_collision(self):
        """PRESERVATION PIN. A dependency edge serializes the pair on both
        settings — sequential work on a shared file stays legal."""
        data = self._pair(
            {"status": "in-progress"},
            {"status": "in-progress", "dependencies": ["story-001"]},
        )
        self.assertEqual(file_domain_lock.collision_report(data, running_only=True), {})

    def test_terminal_story_holds_nothing_on_either_setting(self):
        """PRESERVATION PIN. done/deferred released their files. A done story
        normally HAS a branch_name, so this also pins that the terminal
        exemption is checked BEFORE the branch discriminator."""
        data = self._pair(
            {"status": "done", "branch_name": "shipped/story-001"},
            {"status": "in-progress"},
        )
        self.assertEqual(file_domain_lock.collision_report(data, running_only=True), {})
        self.assertEqual(file_domain_lock.collision_report(data), {})


class TestEditStoryAmendmentAgainstParkedClaim(_SMMTestCase):
    """The measured bug: a running story could not amend its domain onto a
    path a never-started story listed."""

    def test_parked_claim_does_not_block_a_domain_amendment(self):
        """NEW BEHAVIOUR. story-001 is running; story-002 is `ready` and has
        never been branched. story-001 may take the path."""
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "in-progress", "src/a.py"),
                    _story("story-002", "ready", _SHARED),
                ]
            ),
        )
        sprint_store.edit_story(
            self.smm_dir,
            "story-001",
            {"file_domain": ["src/a.py — a", f"{_SHARED} — amended"]},
        )
        story = sprint_store.get_story(self.smm_dir, "story-001")
        self.assertIn(f"{_SHARED} — amended", story["file_domain"])

    def test_live_claim_still_blocks_a_domain_amendment(self):
        """PRESERVATION PIN. Same amendment against a RUNNING claimant is
        still refused — the relaxation is about lifecycle, not about giving up
        the guarantee."""
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "in-progress", "src/a.py"),
                    _story("story-002", "in-progress", _SHARED),
                ]
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            sprint_store.edit_story(
                self.smm_dir,
                "story-001",
                {"file_domain": ["src/a.py — a", f"{_SHARED} — amended"]},
            )
        msg = str(ctx.exception)
        self.assertIn(_SHARED, msg)
        self.assertIn("story-001", msg)
        self.assertIn("story-002", msg)


class TestAuthoringKeepsStrictSemantics(_SMMTestCase):
    """`sprint_save.run()` is the OTHER caller of introduced_collisions.
    Authoring is when disjointness is decided, and every story in a freshly
    authored sprint is parked — so a blanket relaxation would make the gate
    report nothing at exactly the moment it exists for."""

    def test_run_refuses_a_freshly_authored_overlapping_sprint(self):
        """PRESERVATION PIN."""
        data = _sprint([_story("story-001", "ready"), _story("story-002", "ready")])
        with self.assertRaises(ValueError) as ctx:
            sprint_save.run(data, self.smm_dir)
        msg = str(ctx.exception)
        self.assertIn(_SHARED, msg)
        self.assertIn("story-001", msg)
        self.assertIn("story-002", msg)
        self.assertFalse((self.smm_dir / "sprint.json").exists())


class TestFrontierKeepsStrictSemantics(_SMMTestCase):
    """`ready_frontier_report` is the schedule-time check, and its frontier is
    dep-satisfied `scheduled` stories — never-started by construction. Asserted
    through the real caller: only that proves the schedule-time path kept the
    strict rule."""

    def test_overlapping_scheduled_frontier_is_not_parallelizable(self):
        """PRESERVATION PIN."""
        sprint_store.save_sprint(
            self.smm_dir,
            _sprint(
                [
                    _story("story-001", "scheduled"),
                    _story("story-002", "scheduled"),
                ]
            ),
        )
        report = sprint_store.ready_frontier_report(self.smm_dir)
        self.assertEqual(report["frontier"], ["story-001", "story-002"])
        self.assertIn(_SHARED, report["overlap"]["collisions"])
        self.assertFalse(report["parallelizable"])


if __name__ == "__main__":
    unittest.main()
