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
    EVENT_TYPE_SESSION_STARTED,
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
# Stale marker sweep tests (story-005)
# ===========================================================================


class TestSessionStartStaleMarkerSweep(_HookTestCase):
    """SessionStart sweeps stuck markers from prior sessions (story-005).

    See ``markers._STALE_SESSION_MARKERS`` for the marker set and the leak
    sources that motivate the sweep.
    """

    def test_fresh_starts_clear_stale_markers(self):
        import session_start

        # Fresh-start sources (startup, clear) sweep stale markers from
        # prior sessions before any logic branches on them.
        cases = [
            (".close-cycle-active", "startup"),
            (".accept", "startup"),
            (".accept-in-flight", "startup"),
            (".close-cycle-active", "clear"),
            (".accept", "clear"),
            (".accept-in-flight", "clear"),
        ]
        for marker_name, source in cases:
            with self.subTest(marker=marker_name, source=source):
                marker = self.smm_dir / marker_name
                marker.write_text("stale")
                session_start.run(
                    {"session_id": "test", "source": source},
                    smm_dir=self.smm_dir,
                )
                self.assertFalse(marker.exists())

    def test_continuations_preserve_markers(self):
        import session_start

        # resume/compact are mid-session continuations — wiping these
        # markers would silently drop work-in-progress (.accept nudge) or
        # defeat the close-cycle stop gate (CLOSE_CYCLE_ACTIVE).
        cases = [
            (".close-cycle-active", "resume"),
            (".accept", "resume"),
            (".accept-in-flight", "resume"),
            (".close-cycle-active", "compact"),
            (".accept", "compact"),
            (".accept-in-flight", "compact"),
        ]
        for marker_name, source in cases:
            with self.subTest(marker=marker_name, source=source):
                marker = self.smm_dir / marker_name
                marker.write_text("in-flight")
                session_start.run(
                    {"session_id": "test", "source": source},
                    smm_dir=self.smm_dir,
                )
                self.assertTrue(marker.exists())
                self.assertEqual(marker.read_text(), "in-flight")

    def test_sweep_is_idempotent_when_no_markers(self):
        import session_start

        session_start.run(
            {"session_id": "test", "source": "startup"},
            smm_dir=self.smm_dir,
        )


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


class TestSessionStartedEmission(_HookTestCase):
    """session_start emits a session_started anchor on fresh MAIN starts
    (decision f248f4c4e29f, supersedes 9933b0ac1549). Main-only (teammates
    return earlier), once per startup/clear; resume, compact, and teammate
    starts emit none. Idempotency is structural — one start event, one emit."""

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"

    def _started(self) -> list[dict]:
        return [e for e in self._read_events() if e.get("type") == "session_started"]

    def test_startup_emits_one_anchor(self):
        import session_start

        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )
        events = self._started()
        self.assertEqual(len(events), 1, f"expected 1 session_started, got {events!r}")
        self.assertEqual(events[0]["content"], "startup")

    def test_clear_emits_one_anchor(self):
        import session_start

        session_start.run({"session_id": "t", "source": "clear"}, smm_dir=self.smm_dir)
        events = self._started()
        self.assertEqual(len(events), 1, f"expected 1 session_started, got {events!r}")
        self.assertEqual(events[0]["content"], "clear")

    def test_resume_emits_none(self):
        import session_start

        session_start.run({"session_id": "t", "source": "resume"}, smm_dir=self.smm_dir)
        self.assertEqual(self._started(), [])

    def test_compact_emits_none(self):
        import session_start

        session_start.run(
            {"session_id": "t", "source": "compact"}, smm_dir=self.smm_dir
        )
        self.assertEqual(self._started(), [])

    def test_teammate_startup_emits_none(self):
        import session_start

        session_start.run(
            {"session_id": "t", "source": "startup", "cwd": self._TEAMMATE_CWD},
            smm_dir=self.smm_dir,
        )
        self.assertEqual(self._started(), [])

    def test_emitted_anchor_is_schema_valid(self):
        """E2E: a fresh main start lands one valid session_started event."""
        import event_schema
        import session_start

        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )
        events = self._started()
        self.assertEqual(len(events), 1)
        self.assertEqual(event_schema.validate_event(events[0]), [])


class TestSessionStartGoalResolution(_HookTestCase):
    """Prior-session goal-resolution re-homed from session_end to the
    SessionStart fresh-start block (M3 story-002). Main-only; the anchor
    carries metadata.resolves for all unresolved prior goals."""

    _TEAMMATE_CWD = "/home/user/project/.claude/worktrees/worktree-story-001/src"

    def _started(self) -> list[dict]:
        return [
            e
            for e in self._read_events()
            if e.get("type") == EVENT_TYPE_SESSION_STARTED
        ]

    def test_fresh_start_resolves_all_prior_unresolved_goals(self):
        """All unresolved prior goals are resolved regardless of agent_id —
        teammates no longer self-resolve, so main owns the whole window."""
        import session_start

        g_main = make_event(EVENT_TYPE_GOAL, content="Main goal", agent_id="xp-kickoff")
        g_team = make_event(
            EVENT_TYPE_GOAL, content="Teammate goal", agent_id="worktree-story-001"
        )
        self._write_events([g_main, g_team])
        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )
        anchors = self._started()
        self.assertEqual(len(anchors), 1)
        resolves = (anchors[0].get("metadata") or {}).get("resolves", [])
        self.assertIn(g_main["id"], resolves)
        self.assertIn(g_team["id"], resolves)

    def test_resolve_prior_goals_pre_anchor_only(self):
        """Pin the pre-anchor-only invariant: any goal emitted AT or AFTER
        the most-recent session_started anchor must NOT be resolved by the
        sweep. Correct-by-luck today only because no caller emits goals
        at SessionStart time; a future SessionStart-time goal emitter
        would otherwise be silently resolved the instant it lands.
        """
        import session_start

        pre_goal = make_event(
            EVENT_TYPE_GOAL, content="Prior session goal", agent_id="xp-kickoff"
        )
        anchor = make_event(EVENT_TYPE_SESSION_STARTED, content="prior session start")
        post_goal = make_event(
            EVENT_TYPE_GOAL,
            content="Active SessionStart-time goal",
            agent_id="xp-kickoff",
        )
        self._write_events([pre_goal, anchor, post_goal])
        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )
        anchors = self._started()
        # _started() picks every session_started — the prior anchor we
        # seeded plus the new one this run emits.
        self.assertEqual(len(anchors), 2)
        new_anchor = anchors[-1]
        resolves = (new_anchor.get("metadata") or {}).get("resolves", [])
        self.assertIn(
            pre_goal["id"],
            resolves,
            "pre-anchor goal must be resolved (prior-session backlog)",
        )
        self.assertNotIn(
            post_goal["id"],
            resolves,
            "post-anchor goal must NOT be resolved (live, same-conversation work)",
        )

    def test_fresh_start_skips_already_resolved_goals(self):
        import session_start

        g = make_event(EVENT_TYPE_GOAL, content="Resolved goal", agent_id="xp-kickoff")
        r = make_event(
            EVENT_TYPE_STATUS,
            content="done",
            working_on=[],
            metadata={"resolves": [g["id"]]},
        )
        self._write_events([g, r])
        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )
        resolves = (self._started()[0].get("metadata") or {}).get("resolves", [])
        self.assertNotIn(g["id"], resolves)

    def test_no_unresolved_goals_anchor_has_no_resolves(self):
        import session_start

        self._write_events([make_event(content="status only")])
        session_start.run(
            {"session_id": "t", "source": "startup"}, smm_dir=self.smm_dir
        )
        self.assertNotIn("resolves", self._started()[0].get("metadata") or {})

    def test_resume_does_not_resolve_goals(self):
        """resume emits no anchor, so no goal-resolution happens."""
        import session_start

        g = make_event(EVENT_TYPE_GOAL, content="Open goal", agent_id="xp-kickoff")
        self._write_events([g])
        session_start.run({"session_id": "t", "source": "resume"}, smm_dir=self.smm_dir)
        self.assertEqual(self._started(), [])

    def test_clear_does_not_resolve_active_goals(self):
        """source='clear' is a mid-session reset: a goal emitted earlier in
        the SAME conversation (e.g. by /xp-kickoff) is still active. Only
        'startup' — a brand-new session whose prior conversation is gone —
        may treat open goals as prior-session backlog. The clear anchor still
        emits, but carries no resolves for the active goal."""
        import session_start

        g = make_event(EVENT_TYPE_GOAL, content="Active goal", agent_id="xp-kickoff")
        self._write_events([g])
        session_start.run({"session_id": "t", "source": "clear"}, smm_dir=self.smm_dir)
        anchors = self._started()
        self.assertEqual(len(anchors), 1)
        resolves = (anchors[0].get("metadata") or {}).get("resolves", [])
        self.assertNotIn(g["id"], resolves)


if __name__ == "__main__":
    unittest.main()
