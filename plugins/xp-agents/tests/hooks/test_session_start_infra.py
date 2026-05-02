#!/usr/bin/env python3
"""Tests for session_start hook: execution plan markers, system context
markers, plugin config validation, teammate session start, teammate guide.

Split from test_session_start.py — core session start behavior stays there.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import plugin_loader
from conftest import _HookTestCase, make_event, write_smm_fixture

# ===========================================================================
# Execution plan / system context marker tests
# ===========================================================================


class TestSessionStartExecutionPlanMarker(_HookTestCase):
    """session_start writes NEEDS_EXECUTION_PLAN marker when missing."""

    def test_startup_no_execution_plan_writes_marker(self):
        """Startup with no execution_plan.md writes NEEDS_EXECUTION_PLAN."""
        import markers
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.NEEDS_EXECUTION_PLAN)
        )

    def test_startup_with_active_plan_no_marker(self):
        """Startup with execution_plan.json with remaining work — no marker."""
        import markers
        import session_start

        plan = {
            "title": "T",
            "sources": [],
            "overview": "",
            "milestones": [
                {
                    "number": 1,
                    "name": "M1",
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
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.NEEDS_EXECUTION_PLAN)
        )

    def test_startup_all_delivered_writes_marker_and_archives(self):
        """All milestones delivered — writes marker and archives plan."""
        import markers
        import session_start

        plan = {
            "title": "T",
            "sources": [],
            "overview": "",
            "milestones": [
                {
                    "number": 1,
                    "name": "M1",
                    "status": "delivered",
                    "delivered_sprint": "sprint-001",
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
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.NEEDS_EXECUTION_PLAN)
        )
        self.assertFalse((self.smm_dir / "execution_plan.json").exists())
        plans_dir = self.smm_dir / "plans"
        self.assertTrue(plans_dir.is_dir())
        archived = list(plans_dir.glob("execution_plan_*.json"))
        self.assertEqual(len(archived), 1)

    def test_resume_does_not_write_execution_plan_marker(self):
        """Resume source does not write NEEDS_EXECUTION_PLAN."""
        import markers
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.NEEDS_EXECUTION_PLAN)
        )


class TestSessionStartSystemContextMarker(_HookTestCase):
    """session_start writes NEEDS_SYSTEM_CONTEXT marker when missing."""

    def test_startup_no_system_context_writes_marker(self):
        """Startup with no system_context.json writes NEEDS_SYSTEM_CONTEXT."""
        import markers
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertTrue(
            markers.marker_exists(self.smm_dir, markers.NEEDS_SYSTEM_CONTEXT)
        )

    def test_startup_with_system_context_no_marker(self):
        """Startup with system_context.json present does NOT write marker."""
        import markers
        import session_start

        self._write_events([make_event()])
        (self.smm_dir / "system_context.json").write_text("{}")
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.NEEDS_SYSTEM_CONTEXT)
        )

    def test_resume_does_not_write_system_context_marker(self):
        """Resume source does not write NEEDS_SYSTEM_CONTEXT."""
        import markers
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.NEEDS_SYSTEM_CONTEXT)
        )


# ===========================================================================
# Plugin config tests
# ===========================================================================


class TestPluginConfig(unittest.TestCase):
    """AC: Plugin loads without errors."""

    def test_plugin_json_valid(self):
        plugin_path = (
            Path(__file__).parent.parent.parent / ".claude-plugin" / "plugin.json"
        )
        with open(plugin_path) as f:
            data = json.load(f)
        self.assertEqual(data["name"], "xp-agents")
        self.assertIn("version", data)
        self.assertNotIn("hooks", data)

    def test_hooks_json_valid(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        self.assertIn("hooks", data)
        self.assertIn("SessionStart", data["hooks"])
        self.assertIn("SessionEnd", data["hooks"])
        self.assertIn("PreCompact", data["hooks"])
        self.assertIn("SubagentStart", data["hooks"])
        self.assertIn("PreToolUse", data["hooks"])
        self.assertIn("PostToolUse", data["hooks"])

    def test_hooks_use_plugin_root_var(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        raw = hooks_path.read_text()
        self.assertNotIn("scripts/", raw.replace("${CLAUDE_PLUGIN_ROOT}/scripts/", ""))

    def test_no_settings_json(self):
        """settings.json should not exist — all config is hardcoded."""
        settings_path = Path(__file__).parent.parent.parent / "settings.json"
        self.assertFalse(settings_path.is_file())


# ===========================================================================
# Teammate SessionStart tests
# ===========================================================================


class TestTeammateSessionStart(_HookTestCase):
    """CLI teammate SessionStart: inject Values + Guide + SMM, skip markers."""

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"

    def setUp(self):
        super().setUp()
        import session_start

        self.session_start = session_start
        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("Python 3.10+ only", "convention")],
        )

    def _run_teammate(self, source="startup", **overrides):
        data = {
            "session_id": "test",
            "source": source,
            "cwd": self._TEAMMATE_CWD,
            **overrides,
        }
        return self.session_start.run(data, smm_dir=self.smm_dir)

    def test_teammate_gets_values_and_guide(self):
        """Teammate gets XP Values + Teammate Guide."""
        result = self._run_teammate()
        self.assertIsNotNone(result)
        self.assertIn("Extreme Programming", result)
        self.assertIn("Teammate Guide", result)

    def test_teammate_gets_smm(self):
        """Teammate gets rendered SMM content."""
        result = self._run_teammate()
        self.assertIn("Ship v1", result)
        self.assertIn("Intent", result)

    def test_teammate_no_gupp(self):
        """Teammate does NOT get kickoff prompt."""
        result = self._run_teammate()
        self.assertNotIn("xp-kickoff", result)

    def test_teammate_no_markers(self):
        """Teammate SessionStart does NOT set any markers."""
        import markers

        self._run_teammate()
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.KICKOFF))
        self.assertFalse(
            markers.marker_exists(self.smm_dir, markers.NEEDS_EXECUTION_PLAN)
        )
        self.assertFalse(markers.marker_exists(self.smm_dir, markers.NEEDS_SPRINT))

    def test_non_teammate_worktree_normal_path(self):
        """Non-teammate worktree gets normal SessionStart behavior."""
        import markers

        self._write_events([make_event()])
        result = self._run_teammate(
            cwd="/home/user/project/.claude/worktrees/explore-abc/src"
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-kickoff", result)
        self.assertTrue(markers.marker_exists(self.smm_dir, markers.KICKOFF))

    def test_teammate_compact_reinjects(self):
        """Compact source for teammates reinjects full context."""
        result = self._run_teammate(source="compact")
        self.assertIsNotNone(result)
        self.assertIn("Extreme Programming", result)
        self.assertIn("Teammate Guide", result)
        self.assertIn("Ship v1", result)

    def test_teammate_gets_system_context(self):
        """Teammate gets system_context.json when present."""
        ctx = {
            "product": "Microservices arch.",
            "architecture_overview": "Test arch.",
            "stack": {"languages": ["Python"]},
            "modules": [],
            "conventions": [],
            "key_decisions": [],
            "sources": [],
            "project_specific": [],
        }
        (self.smm_dir / "system_context.json").write_text(json.dumps(ctx))
        result = self._run_teammate()
        self.assertIn("System Context", result)
        self.assertIn("Microservices arch.", result)

    def test_teammate_no_system_context_ok(self):
        """Teammate works without system_context.json."""
        result = self._run_teammate()
        self.assertNotIn("System Context", result)
        self.assertIn("Extreme Programming", result)


# ===========================================================================
# Teammate guide content tests
# ===========================================================================


class TestTeammateGuideContent(unittest.TestCase):
    """TEAMMATE_GUIDE.md has required content for CLI teammates."""

    @classmethod
    def setUpClass(cls):
        cls.guide = plugin_loader.load_teammate_guide()
        assert cls.guide, "load_teammate_guide() returned None"

    def test_has_full_review_cycle(self):
        """Guide includes full review cycle commands."""
        self.assertIn("/simplify", self.guide)
        self.assertIn("/xp-quality-review", self.guide)

    def test_has_tdd_discipline(self):
        """Guide includes TDD discipline."""
        self.assertIn("TDD", self.guide)

    def test_has_event_recording(self):
        """Guide includes event recording via append.sh."""
        self.assertIn("append.sh", self.guide)

    def test_has_commit_conventions(self):
        """Guide includes commit conventions."""
        self.assertIn("ruff format", self.guide)

    def test_no_plan_mode(self):
        """Guide does NOT mention plan mode or kickoff."""
        guide_lower = self.guide.lower()
        self.assertNotIn("plan mode", guide_lower)
        self.assertNotIn("kickoff", guide_lower)


if __name__ == "__main__":
    unittest.main()
