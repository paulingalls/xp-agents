#!/usr/bin/env python3
"""Integration tests for xp-assign preload with multi-story sprints.

Split from test_assign.py — preload-specific tests.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import (
    _IntegrationTestCase,
    _s,
    _sprint_json,
    write_smm_fixture,
)


def _extract_preload_var(stdout: str, name: str) -> str | None:
    """Extract a VAR=value from preload stdout. Returns value or None."""
    prefix = f"{name}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1]
    return None


def _multi_story_sprint_worktree() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "User registration",
                "ready",
                file_domain=["src/auth/register.py", "tests/test_register.py"],
            ),
            _s(
                "story-002",
                "Admin dashboard",
                "ready",
                file_domain=["src/admin/dashboard.py", "tests/test_dashboard.py"],
            ),
        ],
        sprint_id="sprint-001",
        started="2026-04-01",
    )


def _multi_story_sprint_solo_deps() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "User model",
                "ready",
                file_domain=["src/models/user.py"],
            ),
            _s(
                "story-002",
                "User API",
                "ready",
                file_domain=["src/api/user.py"],
                dependencies=["story-001"],
            ),
        ],
        sprint_id="sprint-002",
        started="2026-04-01",
    )


def _multi_story_sprint_all_small() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "Fix typo",
                "ready",
                file_domain=["src/ui/header.py"],
            ),
            _s(
                "story-002",
                "Update readme",
                "ready",
                file_domain=["docs/README.md"],
            ),
        ],
        sprint_id="sprint-003",
        started="2026-04-01",
    )


def _multi_story_sprint_no_domains() -> str:
    return _sprint_json(
        [
            _s("story-001", "Feature A", "ready"),
            _s("story-002", "Feature B", "ready"),
        ],
        sprint_id="sprint-004",
        started="2026-04-01",
    )


def _multi_story_sprint_overlapping_domains() -> str:
    return _sprint_json(
        [
            _s(
                "story-001",
                "Auth flow",
                "ready",
                file_domain=["src/auth/login.py", "src/shared/utils.py"],
            ),
            _s(
                "story-002",
                "Password reset",
                "ready",
                file_domain=["src/auth/reset.py", "src/shared/utils.py"],
            ),
        ],
        sprint_id="sprint-005",
        started="2026-04-01",
    )


_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PRELOAD_SCRIPT = _PLUGIN_ROOT / "skills" / "xp-assign" / "scripts" / "preload.sh"


class TestPreloadMultiStorySprint(_IntegrationTestCase):
    """Preload with various multi-story sprint configurations."""

    def _write_sprint(self, sprint_json: str) -> None:
        (self.smm_dir / "sprint.json").write_text(sprint_json)

    def test_preload_with_worktree_eligible_sprint(self):
        self._write_sprint(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_preload_with_dependency_chain_sprint(self):
        self._write_sprint(_multi_story_sprint_solo_deps())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_all_small_stories(self):
        self._write_sprint(_multi_story_sprint_all_small())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_no_file_domains(self):
        self._write_sprint(_multi_story_sprint_no_domains())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_with_overlapping_domains(self):
        self._write_sprint(_multi_story_sprint_overlapping_domains())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SPRINT_FILE=", result.stdout)

    def test_preload_without_sprint_no_sprint_file(self):
        sprint_path = self.smm_dir / "sprint.json"
        if sprint_path.exists():
            sprint_path.unlink()
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("SPRINT_FILE=", result.stdout)
        self.assertIn("SMM_DIR=", result.stdout)

    def test_sprint_file_path_is_readable(self):
        self._write_sprint(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        sprint_path = _extract_preload_var(result.stdout, "SPRINT_FILE")
        assert sprint_path is not None, "SPRINT_FILE= not found in output"
        sprint_file = Path(sprint_path)
        self.assertTrue(sprint_file.is_file())

        content = sprint_file.read_text()
        self.assertIn("sprint-001", content)
        self.assertIn("User registration", content)


class TestRenderedSprintForModeSelection(_IntegrationTestCase):
    """Verify rendered sprint content contains data for mode selection."""

    def _get_rendered_sprint(self, sprint_json: str) -> str:
        (self.smm_dir / "sprint.json").write_text(sprint_json)
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        sprint_path = _extract_preload_var(result.stdout, "SPRINT_FILE")
        assert sprint_path is not None, "SPRINT_FILE= not found"
        return Path(sprint_path).read_text()

    def test_rendered_sprint_includes_file_domains(self):
        content = self._get_rendered_sprint(_multi_story_sprint_worktree())
        self.assertIn("src/auth/register.py", content)
        self.assertIn("src/admin/dashboard.py", content)

    def test_rendered_sprint_includes_dependencies(self):
        content = self._get_rendered_sprint(_multi_story_sprint_solo_deps())
        self.assertIn("story-001", content)

    def test_rendered_sprint_includes_sizes(self):
        content = self._get_rendered_sprint(_multi_story_sprint_all_small())
        self.assertIn("S", content)

    def test_rendered_sprint_shows_overlapping_domains(self):
        content = self._get_rendered_sprint(_multi_story_sprint_overlapping_domains())
        self.assertIn("src/shared/utils.py", content)

    def test_rendered_sprint_empty_domains_visible(self):
        content = self._get_rendered_sprint(_multi_story_sprint_no_domains())
        self.assertIn("Feature A", content)
        self.assertIn("Feature B", content)


class TestPreloadE2EPipeline(_IntegrationTestCase):
    """Full E2E: init SMM, seed sprint, run preload, verify output paths."""

    def _seed_plan(self, content: str = "# Test Plan\n## Step 1\nDo things\n"):
        plan_file = self.smm_dir / "test-plan.md"
        plan_file.write_text(content)
        (self.smm_dir / ".last-plan-path").write_text(str(plan_file))
        return plan_file

    def test_full_pipeline_with_smm_and_sprint(self):
        write_smm_fixture(
            self.smm_dir,
            intent=[("Build auth system", "goal")],
            constraints=[("TDD always", "convention")],
        )
        (self.smm_dir / "sprint.json").write_text(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        self.assertIn("SMM_DIR=", output)
        self.assertIn("SMM_FILE=", output)
        self.assertIn("SPRINT_FILE=", output)

        smm_dir_val = _extract_preload_var(output, "SMM_DIR")
        self.assertEqual(smm_dir_val, str(self.smm_dir))

    def test_full_pipeline_smm_only_no_sprint(self):
        write_smm_fixture(self.smm_dir, wisdom=["Small commits"])
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SMM_DIR=", result.stdout)
        self.assertIn("SMM_FILE=", result.stdout)
        self.assertNotIn("SPRINT_FILE=", result.stdout)

    def test_preload_plan_only_no_sprint(self):
        self._seed_plan()
        sprint_path = self.smm_dir / "sprint.json"
        if sprint_path.exists():
            sprint_path.unlink()

        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        self.assertIn("SMM_DIR=", output)
        self.assertIn("PLAN_FILE=", output)
        self.assertNotIn("SPRINT_FILE=", output)

        plan_path = _extract_preload_var(output, "PLAN_FILE")
        assert plan_path is not None
        self.assertTrue(Path(plan_path).is_file())

    def test_preload_plan_before_sprint_in_output(self):
        self._seed_plan()
        (self.smm_dir / "sprint.json").write_text(_multi_story_sprint_worktree())
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = result.stdout
        plan_pos = output.find("PLAN_FILE=")
        sprint_pos = output.find("SPRINT_FILE=")
        self.assertGreaterEqual(plan_pos, 0)
        self.assertGreaterEqual(sprint_pos, 0)
        self.assertLess(plan_pos, sprint_pos)

    def test_preload_clears_assign_pending_marker(self):
        marker = self.smm_dir / ".assign-pending"
        marker.write_text("gate-id")
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())

    def test_preload_outputs_plugin_root(self):
        result = self._run_preload(_PRELOAD_SCRIPT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PLUGIN_ROOT=", result.stdout)


if __name__ == "__main__":
    unittest.main()
