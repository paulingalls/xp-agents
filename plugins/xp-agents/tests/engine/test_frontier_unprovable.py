#!/usr/bin/env python3
"""ready_frontier_report's unscoped verdict (story-019).

An empty file_domain resolves to no paths, so intersecting it against any
other domain is the empty set — read as "disjoint" unless called out on its
own. `unscoped` is that third answer: distinct from proven-disjoint,
proven-overlapping, and `glob_forced`. Every scenario pairs the unprovable
assertion with a permissive control run through the SAME call, so a
hard-wired False verdict cannot pass silently.

test_sprint_frontier.py is a regression pin at its exact line ceiling and
must keep passing unedited — new verdict coverage lives here instead.
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


class TestFrontierUnscopedVerdict(_SMMTestCase):
    def _report(self, stories):
        import sprint_store

        sprint = _make_sprint(stories=stories)
        (self.smm_dir / "sprint.json").write_text(json.dumps(sprint))
        return sprint_store.ready_frontier_report(self.smm_dir)

    def test_disjoint_scoped_pair_stays_parallelizable(self):
        # The permissive control: two non-empty, non-overlapping domains
        # must still read as parallelizable. Without this alongside the
        # unscoped tests below, a verdict hard-wired to False would pass
        # them equally well.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["b.py — y"],
                ),
            ]
        )
        self.assertTrue(report["parallelizable"])
        self.assertNotIn("unscoped", report["overlap"])

    def test_one_unscoped_story_forces_solo_and_is_named(self):
        # AC-1 + AC-3: an empty file_domain forces solo, and the report
        # names the offending story rather than a generic overlap.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["a.py — x"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=[],
                ),
            ]
        )
        self.assertFalse(report["parallelizable"])
        self.assertEqual(report["overlap"]["unscoped"], ["story-002"])
        self.assertEqual(report["overlap"]["collisions"], {})
        self.assertFalse(report["overlap"]["glob_forced"])

    def test_glob_domain_stays_distinct_from_unscoped(self):
        # glob_forced and unscoped must be tellable apart — the whole point
        # of a sibling key rather than a folded "unprovable" reason.
        report = self._report(
            [
                _make_story(
                    id="story-001",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["src/*"],
                ),
                _make_story(
                    id="story-002",
                    status="scheduled",
                    dependencies=[],
                    file_domain=["docs/api.md"],
                ),
            ]
        )
        self.assertFalse(report["parallelizable"])
        self.assertTrue(report["overlap"]["glob_forced"])
        self.assertNotIn("unscoped", report["overlap"])

    def test_three_stories_all_unscoped_is_not_parallelizable(self):
        # Regression pin for the measured instance: story-004/005/006 each
        # declared file_domain=[], and the frontier reported
        # PARALLELIZABLE=true — offering a three-story teammate batch for
        # stories that would have collided. Must now report unprovable.
        report = self._report(
            [
                _make_story(
                    id="story-004", status="scheduled", dependencies=[], file_domain=[]
                ),
                _make_story(
                    id="story-005", status="scheduled", dependencies=[], file_domain=[]
                ),
                _make_story(
                    id="story-006", status="scheduled", dependencies=[], file_domain=[]
                ),
            ]
        )
        self.assertEqual(report["frontier"], ["story-004", "story-005", "story-006"])
        self.assertFalse(report["parallelizable"])
        self.assertEqual(
            report["overlap"]["unscoped"], ["story-004", "story-005", "story-006"]
        )


if __name__ == "__main__":
    unittest.main()
