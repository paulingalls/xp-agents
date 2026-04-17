#!/usr/bin/env python3
"""Tests for session_start hook: path validation, SMM dir validation,
session start behavior, customer nudge, behavioral guide, plugin config.

Sprint detection and compact-source tests in test_session_start_sprint.py.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
from conftest import _HookTestCase, make_event, write_smm_fixture

# ===========================================================================
# session_start.py tests — path validation
# ===========================================================================


class TestSessionStartPathValidation(_HookTestCase):
    """Test session_start degrades gracefully with bad plugin root."""

    def test_nonexistent_plugin_root(self):
        import session_start

        # Pass smm_dir explicitly so a faulty derivation path can't escape
        # the test's temp dir if validation/derivation logic regresses.
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent/path"}):
            result = session_start.run(
                {"session_id": "test", "source": "startup"},
                smm_dir=self.smm_dir,
            )
        # Should degrade gracefully, not crash
        self.assertIsNotNone(result)


class TestNoSmmLeakOnFallback(_HookTestCase):
    """Regression: in-process hook calls with smm_dir=None used to derive a
    real SMM via init.sh (git fallback) and write markers there — silently
    contaminating the developer's live SMM every time tests ran. Conftest
    pins SMM_DIR per test to prevent this. Without that guard, a startup
    SessionStart with smm_dir=None would call init.sh → write markers
    outside the test's temp dir."""

    def test_in_process_run_with_none_does_not_escape_temp(self):
        import session_start

        kickoff_marker = self.smm_dir / ".needs-kickoff"
        self.assertFalse(kickoff_marker.exists())

        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=None,
        )

        self.assertTrue(
            kickoff_marker.exists(),
            "marker should have been written inside test's temp SMM, "
            "not leaked to the developer's live SMM via init.sh fallback",
        )


class TestSmmDirValidation(_HookTestCase):
    """Tests for _common.validate_smm_dir."""

    def test_rejects_nonexistent(self):
        fake = Path(tempfile.mkdtemp()) / "nonexistent"
        with self.assertRaises(ValueError):
            _common.validate_smm_dir(fake)

    def test_rejects_world_writable(self):
        self.smm_dir.chmod(0o777)
        try:
            with self.assertRaises(ValueError):
                _common.validate_smm_dir(self.smm_dir)
        finally:
            self.smm_dir.chmod(0o700)

    def test_accepts_valid_dir(self):
        self.smm_dir.chmod(0o700)
        _common.validate_smm_dir(self.smm_dir)


# ===========================================================================
# session_start.py tests
# ===========================================================================


class TestSessionStart(_HookTestCase):
    def test_xp_agent_skips(self):
        import session_start

        result = session_start.run(
            {"session_id": "test", "source": "startup", "agent_type": "xp-nav"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNone(result)

    def test_clear_source_returns_context(self):
        """clear is a fresh start — should return GUPP + skills."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "clear"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-kickoff", result)

    def test_clear_source_sets_marker_with_clear(self):
        """clear should set .needs-kickoff marker with 'clear' content."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "clear"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-kickoff"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text(), "clear")

    def test_startup_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("xp-kickoff", result)

    def test_compact_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("Shared Mental Model", result)

    def test_resume_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)

    def test_gupp_in_output(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("xp-kickoff", result)

    def test_skills_in_output(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("xp-kickoff", result)

    def test_no_retro_instruction_in_output(self):
        import session_start

        # Retro logic moved to retrospective.py — session_start should not
        # include retro instructions regardless of event count
        events = [make_event(content=f"event {i}") for i in range(6)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("Run a retrospective", result)
        self.assertNotIn("Action Required", result)

    def test_graceful_no_smm_dir(self):
        import session_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Mock resolve_plugin_root to prevent init.sh from resolving
        # the real project's SMM dir (which would leak a marker file)
        with patch.object(_common, "resolve_plugin_root", return_value=fake_dir):
            result = session_start.run(
                {"session_id": "test", "source": "startup"},
                smm_dir=fake_dir,
            )
        self.assertIsNotNone(result)
        self.assertIn("SMM init failed", result)

    def test_empty_events_file(self):
        import session_start

        # events.jsonl exists but is empty
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # Should still return GUPP and skills even with empty SMM
        self.assertIsNotNone(result)
        self.assertIn("xp-kickoff", result)

    def test_multiple_events_returns_gupp(self):
        import session_start

        events = [make_event(content=f"event {i}") for i in range(10)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # SMM deferred to kickoff — only GUPP + skills here
        self.assertIn("xp-kickoff", result)

    def test_writes_needs_session_review_marker(self):
        """session_start writes .needs-kickoff marker with source."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-kickoff"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text(), "startup")

    def test_resume_does_not_set_marker(self):
        """resume is mid-session — should NOT set .needs-kickoff."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-kickoff"
        self.assertFalse(marker.exists())

    def test_compact_does_not_set_marker(self):
        """compact is mid-session — should NOT set .needs-kickoff."""
        import session_start

        self._write_events([make_event()])
        session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        marker = self.smm_dir / ".needs-kickoff"
        self.assertFalse(marker.exists())

    def test_no_smm_in_context(self):
        """session_start should NOT inject SMM content into context."""
        import session_start

        self._write_events([make_event("goal", content="Ship v1")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("<smm-context>", result)
        self.assertNotIn("Project Goals", result)

    def test_no_goal_nudge_in_context(self):
        """Goal nudge removed — handled by /xp-kickoff."""
        import session_start

        self._write_events([make_event("status", content="working")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("xp-goal-collection", result)


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
        import json

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
        import json

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
        """Startup with no system_context.md writes NEEDS_SYSTEM_CONTEXT."""
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
        """Startup with system_context.md present does NOT write marker."""
        import markers
        import session_start

        self._write_events([make_event()])
        (self.smm_dir / "system_context.md").write_text("# System Context\n")
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
# M6.5: Customer nudge tests
# ===========================================================================


class TestSessionStartCustomerNudge(_HookTestCase):
    """M6.5: session_start.py should nudge goal-collection / question-triage."""

    def test_no_goal_nudge_removed(self):
        """Goal nudge removed — handled by /xp-kickoff."""
        import session_start

        self._write_events([make_event("status", content="working")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("xp-goal-collection", result)

    def test_no_question_nudge_removed(self):
        """Question nudge removed — handled by /xp-kickoff."""
        import session_start

        self._write_events(
            [
                make_event("goal", content="Build the app"),
                make_event(
                    "question",
                    content="Which DB?",
                    priority=_common.PRIORITY_BLOCKING,
                ),
            ]
        )
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("xp-question-triage", result)


# ===========================================================================
# session_start XP values injection tests
# ===========================================================================


class TestSessionStartXPValues(_HookTestCase):
    """XP values injected at session start for all sources."""

    def test_startup_includes_xp_values(self):
        """session_start should include XP values on startup."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIsNotNone(result)
        self.assertIn("XP Values", result)
        self.assertIn("Courage", result)

    def test_startup_no_process_guide(self):
        """session_start should NOT include process guide (deferred to kickoff)."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("EnterPlanMode", result)

    def test_compact_includes_xp_values_and_process(self):
        """compact re-injects XP values + process guide (context lost)."""
        import session_start

        self._write_events([make_event()])
        write_smm_fixture(self.smm_dir, intent=[("Ship v1", "goal")])
        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("XP Values", result)
        self.assertIn("EnterPlanMode", result)

    def test_session_start_includes_skills(self):
        """Output should still contain skill names."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertIn("xp-kickoff", result)

    def test_no_smm_in_session_start(self):
        """SMM is no longer injected by session_start (deferred to kickoff)."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        self.assertNotIn("<smm-context>", result)


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
        # hooks/hooks.json is auto-discovered; must NOT be in manifest
        self.assertNotIn("hooks", data)

    def test_hooks_json_valid(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        with open(hooks_path) as f:
            data = json.load(f)
        self.assertIn("hooks", data)
        # All lifecycle + core hooks registered
        self.assertIn("SessionStart", data["hooks"])
        self.assertIn("SessionEnd", data["hooks"])
        self.assertIn("PreCompact", data["hooks"])
        self.assertIn("SubagentStart", data["hooks"])
        self.assertIn("PreToolUse", data["hooks"])
        self.assertIn("PostToolUse", data["hooks"])

    def test_hooks_use_plugin_root_var(self):
        hooks_path = Path(__file__).parent.parent.parent / "hooks" / "hooks.json"
        raw = hooks_path.read_text()
        # All command paths must use ${CLAUDE_PLUGIN_ROOT}
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

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/teammate-story-001/src"

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
        self.assertIn("XP Values", result)
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
        self.assertIn("XP Values", result)
        self.assertIn("Teammate Guide", result)
        self.assertIn("Ship v1", result)

    def test_teammate_gets_system_context(self):
        """Teammate gets system_context.md when present."""
        (self.smm_dir / "system_context.md").write_text("Microservices arch.\n")
        result = self._run_teammate()
        self.assertIn("System Context", result)
        self.assertIn("Microservices arch.", result)

    def test_teammate_no_system_context_ok(self):
        """Teammate works without system_context.md."""
        result = self._run_teammate()
        self.assertNotIn("System Context", result)
        self.assertIn("XP Values", result)


# ===========================================================================
# Teammate guide content tests
# ===========================================================================


class TestTeammateGuideContent(unittest.TestCase):
    """TEAMMATE_GUIDE.md has required content for CLI teammates."""

    @classmethod
    def setUpClass(cls):
        cls.guide = _common.load_teammate_guide()
        assert cls.guide, "load_teammate_guide() returned None"

    def test_has_full_review_cycle(self):
        """Guide includes full review cycle commands."""
        self.assertIn("/simplify", self.guide)
        self.assertIn("/xp-quality-review", self.guide)
        self.assertIn("/xp-security-triage", self.guide)

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
