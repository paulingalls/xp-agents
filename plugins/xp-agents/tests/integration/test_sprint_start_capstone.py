#!/usr/bin/env python3
"""M-3 capstone: sprint-start surface-coverage + auto-capstone, end-to-end.

Exercises Milestone-3's two shipped primitives against the milestone's `done`
criteria — independent capabilities the sprint-start skill composes, not an
output-chained pipeline:

  - story-002: surface_coverage.uncovered_touched_surfaces returns the touched
    surfaces a coverage concern would fire for (gap or absent — not covered).
  - story-001: sprint_store.build_capstone_story produces a ready,
    behavior-shaped capstone (over all touched surfaces) depending on every
    sibling, which then round-trips through save_sprint/load_sprint.

Capstone discipline: stories 001-003 are already done, so this passes on
first write — the red it guards is a regression in these primitives, not a
red->green cycle.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from _system_context_fixtures import valid_doc
from conftest import _IntegrationTestCase, make_sprint_dict, make_story_dict
from system_context_schema import SYSTEM_CONTEXT_FILENAME

_MILESTONE_NAME = "Milestone 3: surface-coverage"


class TestSprintStartCapstone(_IntegrationTestCase):
    def _seed_surfaces(self) -> None:
        surfaces = [
            {"name": "cli", "signals": ["x"], "status": "covered"},
            {"name": "api", "signals": ["x"], "status": "gap"},
        ]
        (self.smm_dir / SYSTEM_CONTEXT_FILENAME).write_text(
            json.dumps(valid_doc(acceptance_surfaces=surfaces))
        )

    def test_uncovered_detection_flags_only_the_gap_surface(self) -> None:
        import surface_coverage

        self._seed_surfaces()
        milestone = {"surfaces_touched": ["cli", "api"]}
        self.assertEqual(
            surface_coverage.uncovered_touched_surfaces(milestone, self.smm_dir),
            ["api"],
        )

    def test_capstone_built_ready_with_per_surface_acs(self) -> None:
        import sprint_store

        capstone = sprint_store.build_capstone_story(
            "story-004",
            _MILESTONE_NAME,
            ["cli", "api"],
            ["story-001", "story-002", "story-003"],
        )
        self.assertEqual(capstone["status"], "ready")
        self.assertEqual(
            capstone["dependencies"], ["story-001", "story-002", "story-003"]
        )
        acs = capstone["acceptance_criteria"]
        # The cross-surface E2E AC heads the list — it's what makes this a
        # capstone (compose end to end) rather than a per-surface story.
        self.assertIsInstance(acs[0], str)
        self.assertTrue(acs[0].startswith("E2E:"))
        surfaces = {a["surface"] for a in acs if isinstance(a, dict)}
        self.assertEqual(surfaces, {"cli", "api"})
        ae = capstone["acceptance_execution"]
        self.assertEqual(ae["type"], "pytest")
        self.assertTrue(ae["command"])  # non-empty placeholder

    def test_assembled_sprint_with_capstone_round_trips(self) -> None:
        import sprint_store

        siblings = [make_story_dict(id="story-001")]
        capstone = sprint_store.build_capstone_story(
            "story-004", _MILESTONE_NAME, ["cli", "api"], ["story-001"]
        )
        sprint = make_sprint_dict(stories=[*siblings, capstone])

        sprint_store.save_sprint(self.smm_dir, sprint)
        reloaded = sprint_store.load_sprint(self.smm_dir)
        assert reloaded is not None
        cap = next(s for s in reloaded["stories"] if s["id"] == "story-004")
        self.assertEqual(cap["title"], f"Capstone: {_MILESTONE_NAME}")
        self.assertEqual(cap["status"], "ready")


if __name__ == "__main__":
    unittest.main()
