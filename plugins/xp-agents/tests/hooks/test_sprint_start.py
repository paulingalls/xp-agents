#!/usr/bin/env python3
"""Tests for save_sprint.py: atomic writer, acceptance flow, milestones.

Preload script tests live in test_sprint_start_preload.py.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, make_milestone_dict
from event_helpers import events_of_type
from event_schema import EVENT_TYPE_CONCERN, event_action

# ===========================================================================
# save_sprint.py -- Atomic writer for sprint.json
# ===========================================================================

_SAVE_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-start"
    / "scripts"
    / "save_sprint.py"
)


class TestSaveSprint(_HookTestCase):
    """Tests for the save_sprint.py atomic writer."""

    def _run_save(self, data: dict) -> None:
        """Import and call save_sprint.run() directly."""
        if not _SAVE_SCRIPT.is_file():
            self.skipTest("save_sprint.py not yet created")
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_sprint")
        importlib.reload(mod)  # ensure fresh import
        mod.run(data, self.smm_dir)

    def _sample_sprint(self, **overrides) -> dict:
        from conftest import _s

        base = {
            "sprint_id": "sprint-001",
            "goal": "Build auth system",
            "started": "2026-04-01",
            "milestone": "",
            "stories": [_s("story-001", "Register", "ready")],
        }
        base.update(overrides)
        return base

    def test_writes_sprint_json(self):
        """Creates sprint.json with given data."""
        data = self._sample_sprint()
        self._run_save(data)
        target = self.smm_dir / "sprint.json"
        self.assertTrue(target.is_file())
        loaded = json.loads(target.read_text())
        self.assertEqual(loaded["sprint_id"], "sprint-001")

    def test_overwrites_existing(self):
        """Replaces existing sprint.json."""
        target = self.smm_dir / "sprint.json"
        target.write_text(json.dumps(self._sample_sprint()))
        updated = self._sample_sprint(goal="Updated")
        self._run_save(updated)
        loaded = json.loads(target.read_text())
        self.assertEqual(loaded["goal"], "Updated")

    def test_rejects_symlink(self):
        """Raises error when sprint.json is a symlink."""
        target = self.smm_dir / "sprint.json"
        real_file = self.smm_dir / "real.json"
        real_file.write_text("{}")
        target.symlink_to(real_file)
        with self.assertRaises((OSError, ValueError)):
            self._run_save(self._sample_sprint())

    def test_content_passthrough(self):
        """All story statuses preserved in JSON."""
        from conftest import _s

        data = self._sample_sprint(
            sprint_id="sprint-002",
            stories=[
                _s("story-001", "Register", "done"),
                _s("story-002", "Login", "deferred"),
                _s("story-003", "Admin list", "ready"),
            ],
        )
        self._run_save(data)
        loaded = json.loads((self.smm_dir / "sprint.json").read_text())
        self.assertEqual(len(loaded["stories"]), 3)
        statuses = [s["status"] for s in loaded["stories"]]
        self.assertEqual(statuses, ["done", "deferred", "ready"])


def _local_sprint(status="done"):
    from conftest import _s

    return {
        "sprint_id": "sprint-001",
        "goal": "Build auth",
        "started": "2026-04-01",
        "milestone": "",
        "stories": [_s("story-001", "login", status)],
    }


class TestSaveSprintAcceptanceFlow(_HookTestCase):
    """save_sprint.py handles .accept marker and iteration_complete."""

    def _run_save(self, data: dict) -> None:
        if not _SAVE_SCRIPT.is_file():
            self.skipTest("save_sprint.py not yet created")
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_sprint")
        importlib.reload(mod)
        mod.run(data, self.smm_dir)

    def _read_events(self) -> list[dict]:
        events_file = self.smm_dir / "events.jsonl"
        if not events_file.exists():
            return []
        text = events_file.read_text().strip()
        if not text:
            return []
        return [json.loads(line) for line in text.split("\n") if line.strip()]

    def test_clears_accept_marker_when_no_in_progress(self):
        """.accept present and no in-progress stories -> cleared."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_local_sprint(status="done"))
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_keeps_accept_marker_when_in_progress_remains(self):
        """.accept present with in-progress stories -> preserved."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_local_sprint(status="in-progress"))
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_no_iteration_complete_without_accept_marker(self):
        """Without .accept marker, no iteration_complete event."""
        self._run_save(_local_sprint(status="done"))
        events = self._read_events()
        iter_events = [e for e in events if event_action(e) == "iteration_complete"]
        self.assertEqual(len(iter_events), 0)

    def test_iteration_complete_recorded_on_accept_flow(self):
        """.accept present -> iteration_complete status event."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_local_sprint(status="done"))
        events = self._read_events()
        iter_events = [e for e in events if event_action(e) == "iteration_complete"]
        self.assertEqual(len(iter_events), 1)

    def test_sprint_complete_nudge_printed(self):
        """Sprint complete in accept flow -> stdout nudge."""
        from contextlib import redirect_stdout
        from io import StringIO

        (self.smm_dir / ".accept").write_text("done")
        buf = StringIO()
        with redirect_stdout(buf):
            self._run_save(_local_sprint(status="done"))
        self.assertIn("Sprint complete", buf.getvalue())
        self.assertIn("xp-sprint-review", buf.getvalue())

    def test_no_nudge_when_sprint_not_complete(self):
        """Accept flow but sprint has ready stories -> no nudge."""
        from contextlib import redirect_stdout
        from io import StringIO

        (self.smm_dir / ".accept").write_text("done")
        buf = StringIO()
        with redirect_stdout(buf):
            self._run_save(_local_sprint(status="ready"))
        self.assertNotIn("Sprint complete", buf.getvalue())

    def test_clears_needs_sprint_marker_with_active_stories(self):
        """NEEDS_SPRINT marker clears with active stories."""
        (self.smm_dir / ".needs-sprint").write_text("startup")
        self._run_save(_local_sprint(status="ready"))
        self.assertFalse((self.smm_dir / ".needs-sprint").exists())

    def test_keeps_needs_sprint_marker_with_no_active_stories(self):
        """NEEDS_SPRINT marker preserved with no active stories."""
        (self.smm_dir / ".needs-sprint").write_text("startup")
        self._run_save(_local_sprint(status="done"))
        self.assertTrue((self.smm_dir / ".needs-sprint").exists())


# ===========================================================================
# save_sprint.py -- Milestone status transition (story-005)
# ===========================================================================


def _plan_with_milestones(milestones: list[dict]) -> dict:
    """Build a valid execution plan dict with given milestones."""
    return {
        "title": "Test Plan",
        "sources": [],
        "overview": "",
        "milestones": milestones,
    }


_make_milestone = make_milestone_dict


class TestSaveSprintMilestoneTransition(_HookTestCase):
    """save_sprint flips target milestone from planned to in-progress."""

    def _run_save(self, data: dict) -> None:
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_sprint")
        importlib.reload(mod)
        mod.run(data, self.smm_dir)

    def _write_plan(self, milestones: list[dict]) -> None:
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_plan_with_milestones(milestones))
        )

    def _load_plan(self) -> dict:
        return json.loads((self.smm_dir / "execution_plan.json").read_text())

    def _sprint(
        self,
        milestone_text: str = "Milestone 1: Kickoff migration",
    ) -> dict:
        from conftest import _s

        return {
            "sprint_id": "sprint-001",
            "goal": "Build X",
            "started": "2026-04-01",
            "milestone": milestone_text,
            "stories": [_s("story-001", "task", "ready")],
        }

    def test_planned_milestone_flipped_to_in_progress(self):
        """planned milestone becomes in-progress after save_sprint."""
        self._write_plan([_make_milestone(number=1, name="Kickoff migration")])
        self._run_save(self._sprint("Milestone 1: Kickoff migration"))

        plan = self._load_plan()
        self.assertEqual(plan["milestones"][0]["status"], "in-progress")

    def test_already_in_progress_is_idempotent(self):
        """Re-running against in-progress milestone is a no-op."""
        self._write_plan(
            [
                _make_milestone(
                    number=1,
                    name="Kickoff migration",
                    status="in-progress",
                )
            ]
        )
        self._run_save(self._sprint("Milestone 1: Kickoff migration"))

        plan = self._load_plan()
        self.assertEqual(plan["milestones"][0]["status"], "in-progress")

    def test_unparseable_milestone_text_records_concern(self):
        """Unparseable milestone text records concern, no crash."""
        self._write_plan([_make_milestone(number=1, name="Kickoff migration")])
        self._run_save(self._sprint("Free-form milestone name without number"))

        # Sprint still written.
        self.assertTrue((self.smm_dir / "sprint.json").is_file())
        # No milestone status changed.
        plan = self._load_plan()
        self.assertEqual(plan["milestones"][0]["status"], "planned")
        # Concern event appended.
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(
            any("milestone" in e.get("content", "").lower() for e in concerns),
            f"expected a milestone-related concern; got {concerns}",
        )

    def test_missing_execution_plan_records_concern(self):
        """Missing execution_plan.json records concern, no crash."""
        self._run_save(self._sprint("Milestone 1: Kickoff migration"))

        self.assertTrue((self.smm_dir / "sprint.json").is_file())
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(
            any("execution plan" in e.get("content", "").lower() for e in concerns),
            f"expected execution-plan concern; got {concerns}",
        )

    def test_leaked_in_progress_milestone_flags_concern(self):
        """Different milestone already in-progress -> concern."""
        self._write_plan(
            [
                _make_milestone(
                    number=1,
                    name="Done work",
                    status="in-progress",
                ),
                _make_milestone(
                    number=2,
                    name="Current sprint",
                ),
            ]
        )
        self._run_save(self._sprint("Milestone 2: Current sprint"))

        plan = self._load_plan()
        statuses = {m["number"]: m["status"] for m in plan["milestones"]}
        self.assertEqual(statuses[2], "in-progress")
        self.assertEqual(statuses[1], "in-progress")

        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        concerns = events_of_type(events, EVENT_TYPE_CONCERN)
        self.assertTrue(
            any(
                "another milestone" in e.get("content", "").lower()
                or "different milestone" in e.get("content", "").lower()
                or "leaked" in e.get("content", "").lower()
                for e in concerns
            ),
            f"expected leaked-milestone concern; got {concerns}",
        )


if __name__ == "__main__":
    unittest.main()
