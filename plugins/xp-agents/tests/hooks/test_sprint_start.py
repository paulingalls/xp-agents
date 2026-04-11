#!/usr/bin/env python3
"""Tests for save_sprint.py and sprint start preload."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _HookTestCase, _IntegrationTestCase

# ===========================================================================
# save_sprint.py — Atomic writer for sprint.md
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

    def _run_save(self, content: str) -> None:
        """Import and call save_sprint.run() directly."""
        if not _SAVE_SCRIPT.is_file():
            self.skipTest("save_sprint.py not yet created")
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_sprint")
        importlib.reload(mod)  # ensure fresh import
        mod.run(content, self.smm_dir)

    def test_writes_sprint_md(self):
        """Creates sprint.md with given content."""
        content = (
            "# Sprint: Build auth system\n\n"
            "- **Sprint ID:** sprint-001\n"
            "- **Started:** 2026-04-01\n\n"
            "## Stories\n\n"
            "### story-001: As a user I can register\n"
            "- **Size:** M\n"
            "- **Status:** ready\n"
        )
        self._run_save(content)
        target = self.smm_dir / "sprint.md"
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(), content)

    def test_overwrites_existing(self):
        """Replaces existing sprint.md content."""
        target = self.smm_dir / "sprint.md"
        target.write_text("old sprint content")
        new_content = "# Sprint: Updated\n"
        self._run_save(new_content)
        self.assertEqual(target.read_text(), new_content)

    def test_rejects_symlink(self):
        """Raises OSError when sprint.md is a symlink."""
        target = self.smm_dir / "sprint.md"
        real_file = self.smm_dir / "real.md"
        real_file.write_text("real")
        target.symlink_to(real_file)
        with self.assertRaises(OSError):
            self._run_save("new content")

    def test_content_passthrough(self):
        """Deferred stories and various statuses are preserved verbatim."""
        content = (
            "# Sprint: Build user management\n\n"
            "- **Sprint ID:** sprint-002\n"
            "- **Started:** 2026-04-01\n\n"
            "## Stories\n\n"
            "### story-001: As a user I can register\n"
            "- **Size:** M\n"
            "- **Status:** done\n\n"
            "### story-002: As a user I can login\n"
            "- **Size:** S\n"
            "- **Status:** deferred\n\n"
            "### story-003: As an admin I can list users\n"
            "- **Size:** L\n"
            "- **Status:** ready\n"
        )
        self._run_save(content)
        self.assertEqual((self.smm_dir / "sprint.md").read_text(), content)


_SPRINT_COMPLETE = (
    "# Sprint: Build auth\n\n"
    "- **Sprint ID:** sprint-001\n"
    "- **Started:** 2026-04-01\n\n"
    "## Stories\n\n"
    "### story-001: login\n"
    "- **Status:** done\n"
)

_SPRINT_IN_PROGRESS_BODY = (
    "# Sprint: Build auth\n\n"
    "- **Sprint ID:** sprint-001\n"
    "- **Started:** 2026-04-01\n\n"
    "## Stories\n\n"
    "### story-001: login\n"
    "- **Status:** in-progress\n"
)

_SPRINT_READY_ONLY_BODY = (
    "# Sprint: Build auth\n\n"
    "- **Sprint ID:** sprint-001\n"
    "- **Started:** 2026-04-01\n\n"
    "## Stories\n\n"
    "### story-001: login\n"
    "- **Status:** ready\n"
)


class TestSaveSprintAcceptanceFlow(_HookTestCase):
    """save_sprint.py handles .accept marker clearing and iteration_complete.

    This replaces the old accept_done.py behavior — save_sprint.py is the
    reliable signal (file write) for acceptance completion.
    """

    def _run_save(self, content: str) -> None:
        if not _SAVE_SCRIPT.is_file():
            self.skipTest("save_sprint.py not yet created")
        sys.path.insert(0, str(_SAVE_SCRIPT.parent))
        import importlib

        mod = importlib.import_module("save_sprint")
        importlib.reload(mod)
        mod.run(content, self.smm_dir)

    def _read_events(self) -> list[dict]:
        events_file = self.smm_dir / "events.jsonl"
        if not events_file.exists():
            return []
        text = events_file.read_text().strip()
        if not text:
            return []
        return [json.loads(line) for line in text.split("\n") if line.strip()]

    def test_clears_accept_marker_when_no_in_progress(self):
        """.accept present and no in-progress stories → marker cleared."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_SPRINT_COMPLETE)
        self.assertFalse((self.smm_dir / ".accept").exists())

    def test_keeps_accept_marker_when_in_progress_remains(self):
        """.accept present with in-progress stories → marker preserved."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_SPRINT_IN_PROGRESS_BODY)
        self.assertTrue((self.smm_dir / ".accept").exists())

    def test_no_iteration_complete_without_accept_marker(self):
        """Without .accept marker, no iteration_complete event is recorded."""
        self._run_save(_SPRINT_COMPLETE)
        events = self._read_events()
        iter_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "iteration_complete"
        ]
        self.assertEqual(len(iter_events), 0)

    def test_iteration_complete_recorded_on_accept_flow(self):
        """.accept present → iteration_complete status event recorded."""
        (self.smm_dir / ".accept").write_text("done")
        self._run_save(_SPRINT_COMPLETE)
        events = self._read_events()
        iter_events = [
            e
            for e in events
            if e.get("metadata", {}).get("action") == "iteration_complete"
        ]
        self.assertEqual(len(iter_events), 1)

    def test_sprint_complete_nudge_printed(self):
        """Sprint becomes complete in accept flow → stdout contains review nudge."""
        from contextlib import redirect_stdout
        from io import StringIO

        (self.smm_dir / ".accept").write_text("done")
        buf = StringIO()
        with redirect_stdout(buf):
            self._run_save(_SPRINT_COMPLETE)
        self.assertIn("Sprint complete", buf.getvalue())
        self.assertIn("xp-sprint-review", buf.getvalue())

    def test_no_nudge_when_sprint_not_complete(self):
        """Acceptance flow but sprint still has ready stories → no nudge."""
        from contextlib import redirect_stdout
        from io import StringIO

        (self.smm_dir / ".accept").write_text("done")
        buf = StringIO()
        with redirect_stdout(buf):
            self._run_save(_SPRINT_READY_ONLY_BODY)
        # .accept clears (no in-progress), but sprint isn't complete
        self.assertNotIn("Sprint complete", buf.getvalue())

    def test_clears_needs_sprint_marker_with_active_stories(self):
        """NEEDS_SPRINT marker clears when sprint has active stories."""
        (self.smm_dir / ".needs-sprint").write_text("startup")
        self._run_save(_SPRINT_READY_ONLY_BODY)
        self.assertFalse((self.smm_dir / ".needs-sprint").exists())

    def test_keeps_needs_sprint_marker_with_no_active_stories(self):
        """NEEDS_SPRINT marker is preserved when no active stories exist."""
        (self.smm_dir / ".needs-sprint").write_text("startup")
        self._run_save(_SPRINT_COMPLETE)
        self.assertTrue((self.smm_dir / ".needs-sprint").exists())


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
        """Shows deferred stories from existing sprint.md."""
        self._write_plan()
        (self.smm_dir / "sprint.md").write_text(
            "# Sprint: Previous\n\n## Stories\n\n"
            "### story-001: As a user I can register\n"
            "- **Status:** done\n\n"
            "### story-002: As a user I can login\n"
            "- **Status:** deferred\n"
        )
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Deferred", result.stdout)

    def test_preload_sprint_count(self):
        """Outputs correct NEXT_SPRINT_ID based on existing sprint events."""
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
