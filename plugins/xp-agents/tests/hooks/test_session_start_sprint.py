#!/usr/bin/env python3
"""Tests for session_start sprint detection and compact-source reinjection.

Split from test_session_start.py to stay under 500-line cap.
Covers: M8a sprint state markers, M10 compact-source sprint reinjection.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    SPRINT_ALL_DONE,
    SPRINT_READY_ONLY,
    _HookTestCase,
    make_event,
    write_smm_fixture,
)


class TestSessionStartSprintDetection(_HookTestCase):
    """M8a: session_start writes sprint state markers on startup/clear."""

    def test_writes_needs_execution_plan_when_missing(self):
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".needs-execution-plan").exists())

    def test_no_execution_plan_marker_when_active_plan(self):
        import json

        import session_start

        plan = {
            "title": "T",
            "sources": [],
            "overview": "",
            "milestones": [
                {
                    "number": 1,
                    "name": "M",
                    "status": "planned",
                    "delivered_sprint": None,
                    "goal": "G",
                    "done": "D",
                    "sources": "",
                    "change_zones": [],
                    "impact_zones": [],
                    "design_details": "",
                    "constraints": [],
                }
            ],
        }
        self._write_events([make_event()])
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".needs-execution-plan").exists())

    def test_writes_needs_sprint_when_missing(self):
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".needs-sprint").exists())

    def test_writes_needs_sprint_when_no_active_stories(self):
        import session_start

        self._write_events([make_event()])
        (self.smm_dir / "sprint.md").write_text(SPRINT_ALL_DONE)
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertTrue((self.smm_dir / ".needs-sprint").exists())

    def test_no_sprint_marker_when_active_stories(self):
        import session_start

        self._write_events([make_event()])
        (self.smm_dir / "sprint.md").write_text(SPRINT_READY_ONLY)
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".needs-sprint").exists())

    def test_no_markers_when_both_exist_with_active(self):
        import json

        import session_start

        plan = {
            "title": "T",
            "sources": [],
            "overview": "",
            "milestones": [
                {
                    "number": 1,
                    "name": "M",
                    "status": "planned",
                    "delivered_sprint": None,
                    "goal": "G",
                    "done": "D",
                    "sources": "",
                    "change_zones": [],
                    "impact_zones": [],
                    "design_details": "",
                    "constraints": [],
                }
            ],
        }
        self._write_events([make_event()])
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(plan))
        (self.smm_dir / "sprint.md").write_text(SPRINT_READY_ONLY)
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".needs-product-spec").exists())
        self.assertFalse((self.smm_dir / ".needs-sprint").exists())

    def test_clears_accept_marker(self):
        import session_start

        self._write_events([make_event()])
        (self.smm_dir / ".accept").write_text("done")
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_resume_does_not_write_sprint_markers(self):
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".needs-product-spec").exists())
        self.assertFalse((self.smm_dir / ".needs-sprint").exists())

    def test_compact_does_not_write_sprint_markers(self):
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse((self.smm_dir / ".needs-product-spec").exists())
        self.assertFalse((self.smm_dir / ".needs-sprint").exists())


# ===========================================================================
# M10: Compact-source sprint reinjection
# ===========================================================================


class TestSessionStartCompactSprint(_HookTestCase):
    """M10: compact source reinjects SMM + sprint.md."""

    def setUp(self):
        super().setUp()
        write_smm_fixture(self.smm_dir, intent=[("Ship v1", "goal")])
        sprint_file = self.smm_dir / "sprint.md"
        sprint_file.write_text("# Sprint: Build API\n\n- **Sprint ID:** sprint-001\n")

    def test_compact_reinjects_smm_content(self):
        """Compact source includes curated SMM content."""
        import session_start

        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)

    def test_compact_does_not_inject_sprint(self):
        """Compact reinjects SMM + process guide, not sprint.md."""
        import session_start

        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertNotIn("sprint-001", result)

    def test_compact_no_sprint_still_works(self):
        """Compact without sprint.md still returns SMM."""
        import session_start

        (self.smm_dir / "sprint.md").unlink()
        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Ship v1", result)
        self.assertNotIn("sprint-001", result)


if __name__ == "__main__":
    unittest.main()
