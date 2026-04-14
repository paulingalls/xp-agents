#!/usr/bin/env python3
"""Tests for plan_cli.py: CLI wrapper for execution plan operations.

Subprocess tests verify exit codes and stdout for key commands.
Store logic is tested in test_execution_plan_store.py.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _SMMTestCase

_CLI = Path(__file__).parent.parent.parent / "smm" / "plan_cli.py"

_VALID_SOURCE = {
    "label": "Design doc",
    "location": "docs/design.md",
    "type": "repo",
    "content": None,
}

_VALID_MILESTONE = {
    "number": 1,
    "name": "Foundation",
    "status": "planned",
    "delivered_sprint": None,
    "goal": "Build the foundation",
    "done": "Foundation is built and tested",
    "sources": "Design doc §Architecture",
    "change_zones": [{"path": "src/foo.py", "note": "new module"}],
    "impact_zones": [{"path": "src/bar.py", "note": "imports foo"}],
    "design_details": "Details here.",
    "constraints": ["Python 3.10+"],
}


def _make_plan(**overrides) -> dict:
    plan = {
        "title": "Test Plan",
        "sources": [_VALID_SOURCE.copy()],
        "overview": "Test overview.",
        "milestones": [_VALID_MILESTONE.copy()],
    }
    plan.update(overrides)
    return plan


def _run_cli(
    args: list[str],
    smm_dir: Path,
    stdin_data: str | None = None,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_CLI), "--smm-dir", str(smm_dir), *args]
    return subprocess.run(
        cmd,
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
    )


class TestExistsCommand(_SMMTestCase):
    def test_exists_when_plan_present(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_not_exists_when_missing(self):
        result = _run_cli(["exists"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestHasRemainingCommand(_SMMTestCase):
    def test_remaining_when_planned(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(["has-remaining"], self.smm_dir)
        self.assertEqual(result.returncode, 0)

    def test_no_remaining_when_all_delivered(self):
        m = _VALID_MILESTONE.copy()
        m["status"] = "delivered"
        m["delivered_sprint"] = "sprint-001"
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(milestones=[m]))
        )
        result = _run_cli(["has-remaining"], self.smm_dir)
        self.assertEqual(result.returncode, 1)

    def test_no_remaining_when_no_plan(self):
        result = _run_cli(["has-remaining"], self.smm_dir)
        self.assertEqual(result.returncode, 1)


class TestCountCommand(_SMMTestCase):
    def test_count_output(self):
        m2 = _VALID_MILESTONE.copy()
        m2["number"] = 2
        m2["status"] = "delivered"
        m2["delivered_sprint"] = "sprint-001"
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(milestones=[_VALID_MILESTONE.copy(), m2]))
        )
        result = _run_cli(["count"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("planned=1", result.stdout)
        self.assertIn("delivered=1", result.stdout)

    def test_count_missing_plan(self):
        result = _run_cli(["count"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("planned=0", result.stdout)


class TestCreateCommand(_SMMTestCase):
    def test_create_plan(self):
        plan = _make_plan(title="New Plan")
        result = _run_cli(["create"], self.smm_dir, json.dumps(plan))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.smm_dir / "execution_plan.json").exists())
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["title"], "New Plan")

    def test_create_invalid_plan(self):
        result = _run_cli(["create"], self.smm_dir, '{"bad": "data"}')
        self.assertNotEqual(result.returncode, 0)

    def test_create_clears_marker(self):
        marker = self.smm_dir / ".needs-execution-plan"
        marker.write_text("startup")
        plan = _make_plan()
        _run_cli(["create"], self.smm_dir, json.dumps(plan))
        self.assertFalse(marker.exists())


class TestAddMilestoneCommand(_SMMTestCase):
    def test_add_milestone(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        new_m = _VALID_MILESTONE.copy()
        new_m["number"] = 2
        new_m["name"] = "Second Milestone"
        result = _run_cli(["add-milestone"], self.smm_dir, json.dumps(new_m))
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(len(loaded["milestones"]), 2)
        self.assertEqual(loaded["milestones"][1]["name"], "Second Milestone")

    def test_add_milestone_no_plan(self):
        result = _run_cli(
            ["add-milestone"],
            self.smm_dir,
            json.dumps(_VALID_MILESTONE),
        )
        self.assertNotEqual(result.returncode, 0)


class TestAddSourceCommand(_SMMTestCase):
    def test_add_source(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        new_src = {
            "label": "New Source",
            "location": "docs/new.md",
            "type": "repo",
            "content": None,
        }
        result = _run_cli(["add-source"], self.smm_dir, json.dumps(new_src))
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(len(loaded["sources"]), 2)


class TestSetOverviewCommand(_SMMTestCase):
    def test_set_overview(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(["set-overview"], self.smm_dir, "New overview text.")
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["overview"], "New overview text.")


class TestUpdateStatusCommand(_SMMTestCase):
    def test_update_to_in_progress(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(["update-status", "1", "in-progress"], self.smm_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "in-progress")

    def test_update_to_delivered(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(
            [
                "update-status",
                "1",
                "delivered",
                "--delivered-sprint",
                "sprint-005",
            ],
            self.smm_dir,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["status"], "delivered")
        self.assertEqual(loaded["milestones"][0]["delivered_sprint"], "sprint-005")

    def test_delivered_without_sprint_fails(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(["update-status", "1", "delivered"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)

    def test_invalid_milestone_number(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(["update-status", "99", "in-progress"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestRenderCommand(_SMMTestCase):
    def test_render_output(self):
        (self.smm_dir / "execution_plan.json").write_text(
            json.dumps(_make_plan(title="My Plan"))
        )
        result = _run_cli(["render"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertIn("# Execution Plan: My Plan", result.stdout)
        self.assertIn("Foundation", result.stdout)

    def test_render_missing_plan(self):
        result = _run_cli(["render"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestArchiveCommand(_SMMTestCase):
    def test_archive_moves_file(self):
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        result = _run_cli(["archive"], self.smm_dir)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.smm_dir / "execution_plan.json").exists())
        self.assertTrue((self.smm_dir / "plans").is_dir())

    def test_archive_missing_plan(self):
        result = _run_cli(["archive"], self.smm_dir)
        self.assertNotEqual(result.returncode, 0)


class TestEditMilestoneCommand(_SMMTestCase):
    def test_edit_milestone_name(self):
        """Edit a simple string field on a milestone."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"name": "Updated Name"})
        result = _run_cli(["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["name"], "Updated Name")

    def test_edit_milestone_change_zones(self):
        """Edit a complex field (list of objects)."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        new_zones = [{"path": "new.py", "note": "added"}]
        patch = json.dumps({"change_zones": new_zones})
        result = _run_cli(["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["change_zones"], new_zones)

    def test_edit_milestone_multiple_fields(self):
        """Patch multiple fields at once."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"goal": "New goal", "done": "New done"})
        result = _run_cli(["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        self.assertEqual(loaded["milestones"][0]["goal"], "New goal")
        self.assertEqual(loaded["milestones"][0]["done"], "New done")

    def test_edit_milestone_invalid_number(self):
        """Non-existent milestone number fails."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"name": "X"})
        result = _run_cli(["edit-milestone", "99"], self.smm_dir, stdin_data=patch)
        self.assertNotEqual(result.returncode, 0)

    def test_edit_milestone_preserves_other_fields(self):
        """Fields not in the patch are preserved."""
        (self.smm_dir / "execution_plan.json").write_text(json.dumps(_make_plan()))
        patch = json.dumps({"name": "New Name"})
        result = _run_cli(["edit-milestone", "1"], self.smm_dir, stdin_data=patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = json.loads((self.smm_dir / "execution_plan.json").read_text())
        # Original goal preserved
        self.assertEqual(loaded["milestones"][0]["goal"], "Build the foundation")


if __name__ == "__main__":
    unittest.main()
