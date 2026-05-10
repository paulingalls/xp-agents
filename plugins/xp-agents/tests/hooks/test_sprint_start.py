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


# ===========================================================================
# save_sprint.py -- Sister-test auto-inclusion (story-001)
# ===========================================================================


class TestSaveSprintSisterTests(_HookTestCase):
    """save_sprint auto-includes existing sister-test paths in file_domain.

    Closes a recurring planner blind spot: when a story's file_domain lists
    `scripts/<x>.py` or `skills/<name>/preload.sh` and the corresponding
    `tests/**/test_<x>*.py` already exists on disk, the validator appends
    it as a sister-test entry so the story doesn't drift on execution.
    """

    def setUp(self):
        super().setUp()
        import tempfile

        self.project_root = Path(tempfile.mkdtemp())
        (self.project_root / "tests" / "hooks").mkdir(parents=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.project_root, ignore_errors=True)
        super().tearDown()

    def _run_save(self, data: dict) -> None:
        if not _SAVE_SCRIPT.is_file():
            self.skipTest("save_sprint.py not yet created")
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_sprint")
        importlib.reload(mod)
        mod.run(data, self.smm_dir, project_root=self.project_root)

    def _sprint_with_domain(self, file_domain: list[str]) -> dict:
        from conftest import _s

        story = _s("story-001", "Sample", "ready")
        story["file_domain"] = file_domain
        return {
            "sprint_id": "sprint-001",
            "goal": "X",
            "started": "2026-04-01",
            "milestone": "",
            "stories": [story],
        }

    def _read_events(self) -> list[dict]:
        events_file = self.smm_dir / "events.jsonl"
        if not events_file.exists():
            return []
        text = events_file.read_text().strip()
        if not text:
            return []
        return [json.loads(line) for line in text.split("\n") if line.strip()]

    def _saved_story(self) -> dict:
        return json.loads((self.smm_dir / "sprint.json").read_text())["stories"][0]

    # --- AC 1: existing sister test gets auto-included ---

    def test_existing_sister_test_for_scripts_source_is_added(self):
        """`plugins/xp-agents/scripts/foo.py` + existing test_foo.py → added."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        data = self._sprint_with_domain(["plugins/xp-agents/scripts/foo.py"])
        self._run_save(data)

        domain = self._saved_story()["file_domain"]
        self.assertEqual(len(domain), 2)
        self.assertEqual(domain[0], "plugins/xp-agents/scripts/foo.py")
        self.assertIn("tests/hooks/test_foo.py", domain[1])
        self.assertIn("sister test for", domain[1])
        self.assertIn("plugins/xp-agents/scripts/foo.py", domain[1])

    def test_sister_test_added_for_preload_source(self):
        """`skills/xp-foo-bar/preload.sh` → match test_foo_bar*.py."""
        (self.project_root / "tests" / "hooks" / "test_foo_bar_preload.py").write_text(
            "# t"
        )
        data = self._sprint_with_domain(["skills/xp-foo-bar/preload.sh"])
        self._run_save(data)

        domain = self._saved_story()["file_domain"]
        self.assertEqual(len(domain), 2)
        self.assertIn("tests/hooks/test_foo_bar_preload.py", domain[1])

    def test_sister_test_path_extracted_from_dashed_entry(self):
        """`<path> — desc` entries: parse path before adding sister."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        data = self._sprint_with_domain(
            ["plugins/xp-agents/scripts/foo.py — refactor X"]
        )
        self._run_save(data)

        domain = self._saved_story()["file_domain"]
        self.assertEqual(len(domain), 2)
        self.assertIn("tests/hooks/test_foo.py", domain[1])
        self.assertIn("plugins/xp-agents/scripts/foo.py", domain[1])

    def test_multiple_matching_tests_all_added(self):
        """Glob picks up every test_<x>*.py — all become sisters."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        (self.project_root / "tests" / "hooks" / "test_foo_extra.py").write_text("# t")
        data = self._sprint_with_domain(["scripts/foo.py"])
        self._run_save(data)

        domain = self._saved_story()["file_domain"]
        self.assertEqual(len(domain), 3)
        joined = "\n".join(domain)
        self.assertIn("tests/hooks/test_foo.py", joined)
        self.assertIn("tests/hooks/test_foo_extra.py", joined)

    def test_no_duplicate_when_test_already_listed(self):
        """If sister-test path already in file_domain, do not re-add."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        data = self._sprint_with_domain(
            [
                "scripts/foo.py",
                "tests/hooks/test_foo.py",
            ]
        )
        self._run_save(data)

        domain = self._saved_story()["file_domain"]
        # Original two entries; nothing added.
        self.assertEqual(len(domain), 2)

    def test_no_duplicate_when_test_already_listed_with_description(self):
        """De-dup respects path part of dashed entries."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        data = self._sprint_with_domain(
            [
                "scripts/foo.py",
                "tests/hooks/test_foo.py — already listed",
            ]
        )
        self._run_save(data)

        self.assertEqual(len(self._saved_story()["file_domain"]), 2)

    # --- AC 2: missing sister test → no scaffolding, no mutation ---

    def test_missing_sister_test_leaves_domain_untouched(self):
        """No test on disk → file_domain unchanged."""
        data = self._sprint_with_domain(["plugins/xp-agents/scripts/missing.py"])
        self._run_save(data)

        domain = self._saved_story()["file_domain"]
        self.assertEqual(domain, ["plugins/xp-agents/scripts/missing.py"])

    def test_no_test_file_scaffolded_on_disk(self):
        """Validator NEVER creates a test file."""
        data = self._sprint_with_domain(["plugins/xp-agents/scripts/missing.py"])
        self._run_save(data)

        # No file should have been created in tests/.
        created = list((self.project_root / "tests").rglob("test_missing*.py"))
        self.assertEqual(created, [])

    def test_non_matching_source_paths_ignored(self):
        """Paths that aren't scripts/<x>.py or skills/<n>/preload.sh skipped."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        data = self._sprint_with_domain(["docs/foo.md", "smm/foo.py", "README.md"])
        self._run_save(data)

        # Only `smm/foo.py` would NOT match (`smm` != `scripts`); none should add.
        self.assertEqual(
            self._saved_story()["file_domain"],
            ["docs/foo.md", "smm/foo.py", "README.md"],
        )

    # --- AC 3: status event records the additions ---

    def test_additions_recorded_as_status_event(self):
        """One or more additions → status event naming them."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        data = self._sprint_with_domain(["plugins/xp-agents/scripts/foo.py"])
        self._run_save(data)

        events = self._read_events()
        status = [
            e
            for e in events
            if e.get("type") == "status"
            and "sister test" in e.get("content", "").lower()
        ]
        self.assertEqual(len(status), 1, f"expected 1 sister-test status; got {events}")
        self.assertIn("test_foo.py", status[0]["content"])

    def test_no_status_event_when_nothing_added(self):
        """Zero additions → no status event."""
        data = self._sprint_with_domain(["plugins/xp-agents/scripts/missing.py"])
        self._run_save(data)

        events = self._read_events()
        sister_events = [
            e for e in events if "sister test" in e.get("content", "").lower()
        ]
        self.assertEqual(sister_events, [])

    # --- AC 4 (E2E): persisted sprint.json contains the additions ---

    def test_persisted_sprint_json_contains_sister_entries(self):
        """End-to-end: on-disk sprint.json reflects auto-added entries."""
        (self.project_root / "tests" / "hooks" / "test_foo.py").write_text("# t")
        data = self._sprint_with_domain(["plugins/xp-agents/scripts/foo.py"])
        self._run_save(data)

        on_disk = json.loads((self.smm_dir / "sprint.json").read_text())
        domain = on_disk["stories"][0]["file_domain"]
        self.assertEqual(len(domain), 2)
        self.assertIn("tests/hooks/test_foo.py", domain[1])


if __name__ == "__main__":
    unittest.main()
