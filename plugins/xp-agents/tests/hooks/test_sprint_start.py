#!/usr/bin/env python3
"""Tests for save_sprint.py and sprint start preload."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _IntegrationTestCase, make_milestone_dict

# ===========================================================================
# save_sprint.py — Atomic writer for sprint.json
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
    """save_sprint.py handles .accept marker clearing and iteration_complete."""

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
        """.accept present and no in-progress stories → cleared."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_local_sprint(status="done"))
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_keeps_accept_marker_when_in_progress_remains(self):
        """.accept present with in-progress stories → preserved."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_local_sprint(status="in-progress"))
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_no_iteration_complete_without_accept_marker(self):
        """Without .accept marker, no iteration_complete event."""
        self._run_save(_local_sprint(status="done"))
        events = self._read_events()
        iter_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "iteration_complete"
        ]
        self.assertEqual(len(iter_events), 0)

    def test_iteration_complete_recorded_on_accept_flow(self):
        """.accept present → iteration_complete status event."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_local_sprint(status="done"))
        events = self._read_events()
        iter_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "iteration_complete"
        ]
        self.assertEqual(len(iter_events), 1)

    def test_sprint_complete_nudge_printed(self):
        """Sprint complete in accept flow → stdout nudge."""
        from contextlib import redirect_stdout
        from io import StringIO

        (self.smm_dir / ".accept").write_text("done")
        buf = StringIO()
        with redirect_stdout(buf):
            self._run_save(_local_sprint(status="done"))
        self.assertIn("Sprint complete", buf.getvalue())
        self.assertIn("xp-sprint-review", buf.getvalue())

    def test_no_nudge_when_sprint_not_complete(self):
        """Accept flow but sprint has ready stories → no nudge."""
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
# save_sprint.py — Milestone status transition (story-005)
# ===========================================================================


def _plan_with_milestones(milestones: list[dict]) -> dict:
    """Build a valid execution plan dict with the given milestones."""
    return {
        "title": "Test Plan",
        "sources": [],
        "overview": "",
        "milestones": milestones,
    }


_make_milestone = make_milestone_dict


class TestSaveSprintMilestoneTransition(_HookTestCase):
    """save_sprint flips the target milestone from planned to in-progress."""

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

    def _sprint(self, milestone_text: str = "Milestone 1: Kickoff migration") -> dict:
        from conftest import _s

        return {
            "sprint_id": "sprint-001",
            "goal": "Build X",
            "started": "2026-04-01",
            "milestone": milestone_text,
            "stories": [_s("story-001", "task", "ready")],
        }

    def test_planned_milestone_flipped_to_in_progress(self):
        """Happy path: planned milestone becomes in-progress after save_sprint."""
        self._write_plan([_make_milestone(number=1, name="Kickoff migration")])
        self._run_save(self._sprint("Milestone 1: Kickoff migration"))

        plan = self._load_plan()
        self.assertEqual(plan["milestones"][0]["status"], "in-progress")

    def test_already_in_progress_is_idempotent(self):
        """Re-running against an already in-progress milestone is a no-op."""
        self._write_plan(
            [
                _make_milestone(
                    number=1,
                    name="Kickoff migration",
                    status="in-progress",
                )
            ]
        )
        # Must not raise.
        self._run_save(self._sprint("Milestone 1: Kickoff migration"))

        plan = self._load_plan()
        self.assertEqual(plan["milestones"][0]["status"], "in-progress")

    def test_unparseable_milestone_text_records_concern_does_not_fail(self):
        """If sprint.milestone doesn't parse to 'Milestone N:', sprint still
        saves, a concern event is appended, and no milestone status changes."""
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
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(
            any("milestone" in e.get("content", "").lower() for e in concerns),
            f"expected a milestone-related concern; got {concerns}",
        )

    def test_missing_execution_plan_records_concern_does_not_fail(self):
        """If execution_plan.json is absent, sprint still saves and a concern
        is recorded. No exception raised."""
        # Intentionally do NOT write execution_plan.json.
        self._run_save(self._sprint("Milestone 1: Kickoff migration"))

        self.assertTrue((self.smm_dir / "sprint.json").is_file())
        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(
            any("execution plan" in e.get("content", "").lower() for e in concerns),
            f"expected an execution-plan-related concern; got {concerns}",
        )

    def test_leaked_in_progress_milestone_flags_concern(self):
        """If a DIFFERENT milestone is already in-progress, we still flip the
        target to in-progress but append a concern about the orphaned one."""
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
        # Milestone 1 status is not mutated here — our job is to flag it.
        self.assertEqual(statuses[1], "in-progress")

        events = [
            json.loads(line)
            for line in (self.smm_dir / "events.jsonl").read_text().splitlines()
            if line.strip()
        ]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(
            any(
                "another milestone" in e.get("content", "").lower()
                or "different milestone" in e.get("content", "").lower()
                or "leaked" in e.get("content", "").lower()
                for e in concerns
            ),
            f"expected leaked-milestone concern; got {concerns}",
        )


# ===========================================================================
# preload.sh — Sprint start preload script
# ===========================================================================

_PRELOAD_SCRIPT = (
    Path(__file__).parent.parent.parent
    / "skills"
    / "xp-sprint-start"
    / "scripts"
    / "preload.sh"
)


class TestSprintStartPreload(_IntegrationTestCase):
    """Tests for the sprint start preload script."""

    def _write_plan(self, milestones=None):
        """Write a valid JSON plan with given milestones."""
        m_base = {
            "goal": "G",
            "done": "D",
            "sources": "",
            "change_zones": [],
            "impact_zones": [],
            "design_details": "",
            "constraints": [],
        }
        if milestones is None:
            milestones = [
                {
                    **m_base,
                    "number": 1,
                    "name": "Auth",
                    "status": "planned",
                    "delivered_sprint": None,
                }
            ]
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(
                {
                    "title": "T",
                    "sources": [],
                    "overview": "",
                    "milestones": milestones,
                }
            )
        )

    def test_preload_outputs_smm_dir(self):
        """Preload output includes SMM_DIR= line."""
        self._write_plan()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_no_execution_plan(self):
        """Outputs error when no execution_plan.json exists."""
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)
        self.assertIn("execution_plan", result.stdout.lower())

    def test_preload_no_planned_milestones(self):
        """Outputs error when plan has only delivered milestones."""
        m_base = {
            "goal": "G",
            "done": "D",
            "sources": "",
            "change_zones": [],
            "impact_zones": [],
            "design_details": "",
            "constraints": [],
        }
        self._write_plan(
            [
                {
                    **m_base,
                    "number": 1,
                    "name": "Auth",
                    "status": "delivered",
                    "delivered_sprint": "sprint-001",
                }
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ERROR", result.stdout)

    def test_preload_with_planned_milestones(self):
        """Outputs path and counts."""
        m_base = {
            "goal": "G",
            "done": "D",
            "sources": "",
            "change_zones": [],
            "impact_zones": [],
            "design_details": "",
            "constraints": [],
        }
        self._write_plan(
            [
                {
                    **m_base,
                    "number": 1,
                    "name": "Auth",
                    "status": "planned",
                    "delivered_sprint": None,
                },
                {
                    **m_base,
                    "number": 2,
                    "name": "Search",
                    "status": "planned",
                    "delivered_sprint": None,
                },
            ]
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("EXECUTION_PLAN=", result.stdout)
        self.assertIn("planned=2", result.stdout)

    def test_preload_existing_sprint_deferred(self):
        """Shows deferred stories from existing sprint.json."""
        from conftest import _s, _sprint_json

        self._write_plan()
        (self.smm_dir / "sprint.json").write_text(
            _sprint_json(
                [
                    _s("story-001", "Register", "done"),
                    _s("story-002", "Login", "deferred"),
                ],
                goal="Previous",
            )
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Deferred", result.stdout)

    def test_preload_sprint_count(self):
        """Outputs correct NEXT_SPRINT_ID from sprint event count."""
        self._write_plan()
        # Seed two sprint-start events
        events = [
            json.dumps(
                {
                    "id": "e1",
                    "ts": "2026-03-01T00:00:00Z",
                    "type": "sprint",
                    "agent_id": "xp-sprint-start",
                    "content": "Sprint 1",
                    "metadata": {"sprint_id": "sprint-001", "action": "start"},
                    "schema_version": 1,
                }
            ),
            json.dumps(
                {
                    "id": "e2",
                    "ts": "2026-03-15T00:00:00Z",
                    "type": "sprint",
                    "agent_id": "xp-sprint-start",
                    "content": "Sprint 2",
                    "metadata": {"sprint_id": "sprint-002", "action": "start"},
                    "schema_version": 1,
                }
            ),
        ]
        (self.smm_dir / "events.jsonl").write_text("\n".join(events) + "\n")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("sprint-003", result.stdout)


if __name__ == "__main__":
    unittest.main()
