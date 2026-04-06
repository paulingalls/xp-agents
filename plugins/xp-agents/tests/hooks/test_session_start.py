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
from conftest import _HookTestCase, make_event

# ===========================================================================
# session_start.py tests — path validation
# ===========================================================================


class TestSessionStartPathValidation(_HookTestCase):
    """Test session_start degrades gracefully with bad plugin root."""

    def test_nonexistent_plugin_root(self):
        import session_start

        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent/path"}):
            result = session_start.run(
                {"session_id": "test", "source": "startup"},
                smm_dir=None,
            )
        # Should degrade gracefully, not crash
        self.assertIsNotNone(result)


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
        self.assertIn("xp-smm-protocol", result)

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
        # Should still return context even without SMM
        self.assertIsNotNone(result)

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
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n\n## Intent\n- Ship v1\n"
        )
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
        self.assertIn("xp-smm-protocol", result)

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

    def test_settings_json_valid(self):
        settings_path = Path(__file__).parent.parent.parent / "settings.json"
        with open(settings_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main()
