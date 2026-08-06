#!/usr/bin/env python3
"""ready_frontier_report's dependency-edge / treat_as_done interaction.

Split out of test_sprint_frontier.py once the always-present `unscoped` key
(story-019 follow-up) pushed that file past its line ceiling — this is a
cohesive group distinct from the collision/glob/unscoped-shape tests that
stayed behind: every test here is about a dependency edge (direct,
transitive, or through treat_as_done) forcing solo even when file domains
are disjoint, never about the overlap dict's shape.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase
from conftest import make_sprint_dict as _make_sprint
from conftest import make_story_dict as _make_story


class TestReadyFrontierReportDependencyEdges(_SMMTestCase):
    """A frontier member depending on another (directly, transitively, or
    only visible via treat_as_done) must read as solo regardless of file
    domains — the antichain guard, not the overlap detail, owns this verdict.
    """

    def _report(self, stories, *, treat_as_done=None):
        import sprint_store

        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        return sprint_store.ready_frontier_report(
            self.smm_dir, treat_as_done=treat_as_done
        )

    def test_treat_as_done_dependent_pair_is_not_parallelizable(self):
        # The repro: 001 scheduled, 002 scheduled deps=[001], both claim
        # shared.py. treat_as_done={001} lifts 002 onto the frontier
        # alongside 001 — a dependency edge, not an independent pair — so
        # parallelizable must be False even though collisions/glob_forced
        # (dependency-aware, unchanged) stay empty/false. Pins that the fix
        # lives at the frontier layer, not the overlap layer.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["shared.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["shared.py"],
                ),
            ],
            treat_as_done={"story-001"},
        )
        self.assertEqual(report["frontier"], ["story-001", "story-002"])
        self.assertFalse(report["parallelizable"])
        self.assertEqual(
            report["overlap"],
            {"collisions": {}, "glob_forced": False, "unscoped": []},
        )

    def test_dependency_edge_forces_solo_even_with_disjoint_domains(self):
        # Same shape, disjoint domains (a.py/b.py). The real reason a
        # dependent frontier can't parallelize is the shared sprint base a
        # promoted dependent gets cut from — not a file collision. Without
        # this test a reader could believe the fix is about file overlap.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["b.py"],
                ),
            ],
            treat_as_done={"story-001"},
        )
        self.assertEqual(report["frontier"], ["story-001", "story-002"])
        self.assertFalse(report["parallelizable"])
        self.assertEqual(
            report["overlap"],
            {"collisions": {}, "glob_forced": False, "unscoped": []},
        )

    def test_transitive_dependency_through_non_frontier_story_forces_solo(self):
        # 001 scheduled; 003 scheduled deps=[001]; 002 scheduled deps=[003];
        # treat_as_done={003}. Frontier is [001, 002] — 003 itself is NOT on
        # the frontier (its own dep, 001, isn't done/overridden) — but 002
        # transitively depends on 001 THROUGH 003. A direct-edge-only check
        # would see no edge between 001 and 002 and wrongly parallelize.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-003"],
                    file_domain=["b.py"],
                ),
                _make_story(
                    id="story-003",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["c.py"],
                ),
            ],
            treat_as_done={"story-003"},
        )
        self.assertEqual(report["frontier"], ["story-001", "story-002"])
        self.assertFalse(report["parallelizable"])

    def test_done_story_with_scheduled_dep_forces_solo(self):
        # No override at all: 001 scheduled (own dep not done, so NOT on
        # frontier — irrelevant to the bug); 002 status=done but its own
        # dependency (003) is still scheduled; 004 scheduled deps=[002].
        # 002 being `done` satisfies 004's dep check with zero override,
        # linking 004 to 003's still-unfinished work through 002. Proves the
        # guard is not treat_as_done-specific.
        report = self._report(
            [
                _make_story(
                    id="story-003",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["c.py"],
                ),
                _make_story(
                    id="story-002",
                    status="done",
                    dependencies=["story-003"],
                    file_domain=["b.py"],
                ),
                _make_story(
                    id="story-004",
                    status="scheduled",
                    dependencies=["story-002"],
                    file_domain=["d.py"],
                ),
            ],
        )
        self.assertEqual(report["frontier"], ["story-003", "story-004"])
        self.assertFalse(report["parallelizable"])

    def test_treat_as_done_still_parallelizes_an_independent_frontier(self):
        # THE NON-REGRESSION PIN. 001 closing (the legitimate treat_as_done
        # use — a just-closed story not yet marked done on disk), 002
        # deps=[001], 004 independent, all disjoint domains. Must stay
        # parallelizable — an over-broad "any override present => solo"
        # fix would wrongly kill this.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="closing",
                    dependencies=[],
                    file_domain=["a.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["b.py"],
                ),
                _make_story(
                    id="story-004",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["d.py"],
                ),
            ],
            treat_as_done={"story-001"},
        )
        self.assertEqual(report["frontier"], ["story-002", "story-004"])
        self.assertTrue(report["parallelizable"])

    def test_dependency_cycle_frontier_is_not_parallelizable(self):
        # A malformed cycle (001 deps=[002], 002 deps=[001]) must terminate
        # and read as "never concurrent" — the conservative answer.
        # treat_as_done lifts both onto the frontier simultaneously.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=["story-002"],
                    file_domain=["a.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=["story-001"],
                    file_domain=["b.py"],
                ),
            ],
            treat_as_done={"story-001", "story-002"},
        )
        self.assertEqual(report["frontier"], ["story-001", "story-002"])
        self.assertFalse(report["parallelizable"])

    def test_treat_as_done_unknown_id_does_not_crash(self):
        # override names an id absent from the sprint — must not raise.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["b.py"],
                ),
            ],
            treat_as_done={"story-999"},
        )
        self.assertEqual(report["frontier"], ["story-001", "story-002"])
        self.assertTrue(report["parallelizable"])


if __name__ == "__main__":
    unittest.main()
