#!/usr/bin/env python3
"""Tests for session_start hook: path validation, SMM dir validation,
session start behavior, customer nudge, XP values injection.

Markers, teammates, plugin config in test_session_start_infra.py.
Sprint detection and compact-source tests in test_session_start_sprint.py.
"""

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
import plugin_loader
from conftest import _HookTestCase, make_event, write_smm_fixture
from event_schema import (
    EVENT_TYPE_GOAL,
    EVENT_TYPE_QUESTION,
    EVENT_TYPE_STATUS,
)

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
        assert result is not None


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
        assert result is not None
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
        assert result is not None
        self.assertIn("xp-kickoff", result)

    def test_compact_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "compact"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("Shared Mental Model", result)

    def test_resume_returns_context(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "resume"},
            smm_dir=self.smm_dir,
        )
        assert result is not None

    def test_gupp_in_output(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("xp-kickoff", result)

    def test_skills_in_output(self):
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
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
        assert result is not None
        self.assertNotIn("Run a retrospective", result)
        self.assertNotIn("Action Required", result)

    def test_graceful_no_smm_dir(self):
        import session_start

        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        # Mock resolve_plugin_root to prevent init.sh from resolving
        # the real project's SMM dir (which would leak a marker file)
        with patch.object(plugin_loader, "resolve_plugin_root", return_value=fake_dir):
            result = session_start.run(
                {"session_id": "test", "source": "startup"},
                smm_dir=fake_dir,
            )
        assert result is not None
        self.assertIn("SMM init failed", result)

    def test_empty_events_file(self):
        import session_start

        # events.jsonl exists but is empty
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        # Should still return GUPP and skills even with empty SMM
        assert result is not None
        self.assertIn("xp-kickoff", result)

    def test_multiple_events_returns_gupp(self):
        import session_start

        events = [make_event(content=f"event {i}") for i in range(10)]
        self._write_events(events)
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
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

    def test_system_message_nudges_kickoff_on_startup(self):
        """startup is a new session — systemMessage should mention /xp-kickoff."""
        import session_start

        msg = session_start._system_message("startup", "9.9.9")
        self.assertIn("xp-kickoff", msg)

    def test_system_message_nudges_kickoff_on_clear(self):
        """clear resets state mid-session — systemMessage should mention /xp-kickoff."""
        import session_start

        msg = session_start._system_message("clear", "9.9.9")
        self.assertIn("xp-kickoff", msg)

    def test_system_message_skips_kickoff_on_compact(self):
        """compact is a continuation — kickoff would re-do work that was just done."""
        import session_start

        msg = session_start._system_message("compact", "9.9.9")
        self.assertNotIn("xp-kickoff", msg)
        self.assertIn("9.9.9", msg)

    def test_system_message_skips_kickoff_on_resume(self):
        """resume is a continuation — same continuation semantics as compact."""
        import session_start

        msg = session_start._system_message("resume", "9.9.9")
        self.assertNotIn("xp-kickoff", msg)
        self.assertIn("9.9.9", msg)

    def test_no_smm_in_context(self):
        """session_start should NOT inject SMM content into context."""
        import session_start

        self._write_events([make_event(EVENT_TYPE_GOAL, content="Ship v1")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertNotIn("<smm-context>", result)
        self.assertNotIn("Project Goals", result)

    def test_no_goal_nudge_in_context(self):
        """Goal nudge removed — handled by /xp-kickoff."""
        import session_start

        self._write_events([make_event(EVENT_TYPE_STATUS, content="working")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertNotIn("xp-goal-collection", result)


# ===========================================================================
# M6.5: Customer nudge tests
# ===========================================================================


class TestSessionStartCustomerNudge(_HookTestCase):
    """M6.5: session_start.py should nudge goal-collection / question-triage."""

    def test_no_goal_nudge_removed(self):
        """Goal nudge removed — handled by /xp-kickoff."""
        import session_start

        self._write_events([make_event(EVENT_TYPE_STATUS, content="working")])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertNotIn("xp-goal-collection", result)

    def test_no_question_nudge_removed(self):
        """Question nudge removed — handled by /xp-kickoff."""
        import session_start

        self._write_events(
            [
                make_event(EVENT_TYPE_GOAL, content="Build the app"),
                make_event(
                    EVENT_TYPE_QUESTION,
                    content="Which DB?",
                    priority=_common.PRIORITY_BLOCKING,
                ),
            ]
        )
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
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
        assert result is not None
        self.assertIn("Extreme Programming", result)
        self.assertIn("Courage", result)

    def test_startup_no_process_guide(self):
        """session_start should NOT include process guide (deferred to kickoff)."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
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
        assert result is not None
        self.assertIn("Extreme Programming", result)
        self.assertIn("EnterPlanMode", result)

    def test_session_start_includes_skills(self):
        """Output should still contain skill names."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertIn("xp-kickoff", result)

    def test_no_smm_in_session_start(self):
        """SMM is no longer injected by session_start (deferred to kickoff)."""
        import session_start

        self._write_events([make_event()])
        result = session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )
        assert result is not None
        self.assertNotIn("<smm-context>", result)


if __name__ == "__main__":
    unittest.main()
