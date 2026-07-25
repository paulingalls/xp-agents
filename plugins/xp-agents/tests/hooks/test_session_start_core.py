#!/usr/bin/env python3
"""Tests for session_start hook: path validation, SMM dir validation, core
run behavior across sources (startup/clear/compact/resume/xp-agent).

Split from test_session_start.py to stay under 500-line cap. Customer nudge,
stale marker sweep, XP values injection, session_started anchor emission, and
prior-session goal resolution are in test_session_start_effects.py.

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
from conftest import _HookTestCase, make_event
from event_schema import (
    EVENT_TYPE_GOAL,
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


class TestInitShResolutionBudget(_HookTestCase):
    """How long SessionStart lets init.sh take before giving up on the plugin.

    The first resolution after an upgrade does not just print a path: it copies
    the WHOLE SMM to the new data root, twice (initial copy plus the pre-rename
    re-sync), inside this very call. A budget sized for a path lookup turns a
    large or network-hosted SMM into "SMM init failed — xp-agents disabled" for
    the entire session — no retrospective, no event log, no commit gate — on the
    one session where the relocation was supposed to happen.
    """

    def _stub_plugin_root(self, body: str) -> Path:
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "smm").mkdir()
        (root / "smm" / "init.sh").write_text(f"#!/bin/bash\n{body}\n")
        return root

    def test_a_slow_first_resolution_is_waited_out(self):
        import session_start

        root = self._stub_plugin_root(f'sleep 6\nprintf "%s" "{self.smm_dir}"')
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": str(root)}):
            self.assertEqual(session_start._resolve_via_init_sh(), self.smm_dir)

    def test_a_hung_resolution_still_gives_up(self):
        """The budget is larger, not gone: a wedged init.sh must not hang the
        session start forever."""
        import session_start

        root = self._stub_plugin_root(f'sleep 30\nprintf "%s" "{self.smm_dir}"')
        with (
            patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": str(root)}),
            patch.object(session_start, "_INIT_SH_TIMEOUT_SECONDS", 0.2),
        ):
            self.assertIsNone(session_start._resolve_via_init_sh())

    def _main_with_resolution(self, resolved):
        """Run main() with the init.sh resolution stubbed to ``resolved``.

        Returns (resolve_mock, hook_output_mock).
        """
        import session_start

        with (
            patch.object(
                session_start, "_resolve_via_init_sh", return_value=resolved
            ) as resolve,
            patch.object(
                session_start._common,
                "read_hook_input",
                return_value={"session_id": "t", "source": "startup"},
            ),
            patch.object(session_start._common, "hook_output") as hook_output,
        ):
            session_start.main()
        return resolve, hook_output

    def test_the_entry_point_resolves_only_once(self):
        """One resolution serves both the run and the advisory.

        Not a micro-optimization: this call can perform the relocation, so a
        second one pays for a whole-SMM copy twice.
        """
        resolve, hook_output = self._main_with_resolution(self.smm_dir)
        self.assertEqual(resolve.call_count, 1)
        hook_output.assert_called_once()

    def test_a_failed_entry_point_resolution_is_not_retried(self):
        """The timeout case is the one that must not double.

        A resolution that returns nothing is overwhelmingly the one that timed
        out, so retrying it inside ``run`` spends the budget twice — 60s inside
        a hook that already gave up at 30 — and then fails anyway. Fail fast to
        the disabled message instead.
        """
        resolve, hook_output = self._main_with_resolution(None)
        self.assertEqual(resolve.call_count, 1)
        self.assertIn("SMM init failed", hook_output.call_args.args[1])

    def test_the_entry_point_does_not_resolve_for_a_teammate(self):
        """A teammate's SessionStart deliberately runs with no SMM dir (handing
        it one injects the whole SMM render into every teammate's context), and
        the advisory is for the human at the lead session — so neither half
        needs the resolution, and a teammate must not pay for one."""
        import session_start

        with (
            patch.object(session_start, "_resolve_via_init_sh") as resolve,
            patch.object(
                session_start.identity, "is_worktree_teammate", return_value=True
            ),
            patch.object(
                session_start._common,
                "read_hook_input",
                return_value={"session_id": "t", "source": "startup"},
            ),
            patch.object(session_start._common, "hook_output"),
        ):
            session_start.main()
        resolve.assert_not_called()

    def test_the_entry_point_does_not_resolve_for_a_nested_xp_agent(self):
        """The recursion guard returns before anything reads the SMM."""
        import session_start

        with (
            patch.object(session_start, "_resolve_via_init_sh") as resolve,
            patch.object(
                session_start._common,
                "read_hook_input",
                return_value={
                    "session_id": "t",
                    "source": "startup",
                    "agent_type": "xp-code-reviewer",
                },
            ),
            patch.object(session_start._common, "hook_output") as hook_output,
        ):
            session_start.main()
        resolve.assert_not_called()
        hook_output.assert_not_called()


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


if __name__ == "__main__":
    unittest.main()
