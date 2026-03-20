#!/usr/bin/env python3
"""Integration tests: session lifecycle hooks.

Tests for SessionStart, SessionEnd, PreCompact, SubagentStart,
and milestone 6/6.5 session-related integration.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, make_event


class TestSessionStartIntegration(_IntegrationTestCase):
    def test_startup_returns_smm_context(self):
        """stdin → session_start.py → stdout with SMM + GUPP."""
        self._seed_events([make_event()])
        result = self._run_script(
            "session_start.py",
            {
                "session_id": "int-test",
                "source": "startup",
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Shared Mental Model", ctx)
        self.assertIn("Resume immediately", ctx)

    def test_compact_source_returns_context(self):
        self._seed_events([make_event()])
        result = self._run_script(
            "session_start.py",
            {
                "session_id": "int-test",
                "source": "compact",
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Shared Mental Model", ctx)

    def test_xp_agent_produces_no_output(self):
        result = self._run_script(
            "session_start.py",
            {
                "session_id": "int-test",
                "source": "startup",
                "agent_type": "xp-housekeeping",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_no_retro_in_session_start_output(self):
        """Retro logic moved to retrospective.py."""
        self._seed_events([make_event(content=f"e{i}") for i in range(6)])
        result = self._run_script(
            "session_start.py",
            {
                "session_id": "int-test",
                "source": "startup",
            },
        )
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("Run a retrospective", ctx)
        self.assertNotIn("Action Required", ctx)


class TestSessionEndIntegration(_IntegrationTestCase):
    def test_appends_session_end_event(self):
        """stdin → session_end.py → session_end event on disk."""
        self._seed_events([make_event(), make_event()])
        result = self._run_script(
            "session_end.py",
            {
                "session_id": "int-test",
                "reason": "user_logout",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

        events = self._read_events()
        se = [e for e in events if e.get("type") == "session_end"]
        self.assertEqual(len(se), 1)
        self.assertIn("user_logout", se[0]["content"])
        self.assertEqual(se[0]["event_count"], 2)
        self.assertIn("duration_seconds", se[0])
        self.assertIsInstance(se[0]["unresolved_items"], list)

    def test_captures_unresolved_questions(self):
        q = make_event("question", priority="\U0001f534", content="Unanswered?")
        self._seed_events([q])
        self._run_script(
            "session_end.py",
            {
                "session_id": "int-test",
                "reason": "timeout",
            },
        )
        events = self._read_events()
        se = next(e for e in events if e.get("type") == "session_end")
        self.assertIn(q["id"], se["unresolved_items"])

    def test_xp_agent_creates_no_events(self):
        self._seed_events([make_event()])
        result = self._run_script(
            "session_end.py",
            {
                "session_id": "int-test",
                "reason": "logout",
                "agent_type": "xp-housekeeping",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        se = [e for e in events if e.get("type") == "session_end"]
        self.assertEqual(len(se), 0)


class TestPreCompactIntegration(_IntegrationTestCase):
    def test_creates_backup_files(self):
        """stdin → pre_compact.py → backup files on disk."""
        self._seed_events([make_event()])
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text("# Test SMM\n")

        result = self._run_script(
            "pre_compact.py",
            {
                "session_id": "int-test",
            },
        )
        self.assertEqual(result.returncode, 0)

        backups_dir = self.smm_dir / "backups"
        self.assertTrue(backups_dir.exists())
        event_backups = list(backups_dir.glob("events-*.jsonl"))
        smm_backups = list(backups_dir.glob("SMM-*.md"))
        self.assertEqual(len(event_backups), 1)
        self.assertEqual(len(smm_backups), 1)
        self.assertEqual(
            event_backups[0].read_text(),
            (self.smm_dir / "events.jsonl").read_text(),
        )

    def test_xp_agent_creates_no_backups(self):
        self._seed_events([make_event()])
        result = self._run_script(
            "pre_compact.py",
            {
                "session_id": "int-test",
                "agent_type": "xp-reviewer",
            },
        )
        self.assertEqual(result.returncode, 0)
        backups_dir = self.smm_dir / "backups"
        self.assertFalse(backups_dir.exists())


class TestSubagentStartIntegration(_IntegrationTestCase):
    def test_returns_smm_and_writes_watermark(self):
        """stdin → subagent_start.py → stdout with SMM content."""
        self._seed_events([make_event(), make_event()])
        # Write a curated SMM file so subagent_start injects it
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n## Intent\n- Ship v1\n"
        )
        result = self._run_script(
            "subagent_start.py",
            {
                "session_id": "int-test",
                "agent_id": "explorer-1",
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Shared Mental Model", ctx)

    def test_xp_agent_produces_no_output(self):
        self._seed_events([make_event()])
        result = self._run_script(
            "subagent_start.py",
            {
                "session_id": "int-test",
                "agent_id": "explorer-1",
                "agent_type": "xp-housekeeping",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        wm_file = self.smm_dir / ".watermark-explorer-1"
        self.assertFalse(wm_file.exists())


class TestMilestone6Integration(_IntegrationTestCase):
    def test_session_start_no_behavioral_guide(self):
        """session_start no longer includes behavioral guide."""
        self._seed_events([make_event()])
        result = self._run_script(
            "session_start.py",
            {"session_id": "int-test", "source": "startup"},
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        # Guide moved to kickoff_done.py
        self.assertNotIn("Honesty Principle", ctx)
        # Skills should still be present
        self.assertIn("smm-protocol", ctx)
        self.assertIn("Resume immediately", ctx)

    def test_skill_files_parseable(self):
        """All skill SKILL.md files exist and are non-trivial."""
        plugin_root = Path(__file__).parent.parent.parent
        for name in ("smm-protocol",):
            skill_file = plugin_root / "skills" / name / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"Missing: {skill_file}")
            content = skill_file.read_text()
            self.assertGreater(len(content), 500, f"{name} too short")
            self.assertTrue(content.startswith("---"), f"{name} missing frontmatter")


class TestMilestone65Integration(_IntegrationTestCase):
    def test_subagent_stop_plan_writes_gate_marker(self):
        """Plan agent_type → writes plan_awaiting_review marker event."""
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "1. Do stuff\n2. More stuff",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        events = self._read_events()
        gate = [e for e in events if "plan_awaiting_review" in e.get("content", "")]
        self.assertEqual(len(gate), 1)

    def test_subagent_stop_no_reviewer_nudge(self):
        """Regular subagent → no reviewer nudge (xp-subagent-reviewer removed)."""
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_retrospective_nudge(self):
        """>=5 events → stdout contains xp-retrospective nudge."""
        self._seed_events([make_event(content=f"e{i}") for i in range(6)])
        result = self._run_script(
            "retrospective.py",
            {"session_id": "int-test", "source": "startup"},
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-retrospective", ctx)

    def test_agent_files_exist(self):
        """All 2 agent .md files exist in agents/ directory."""
        agents_dir = Path(__file__).parent.parent.parent / "agents"
        for name in (
            "xp-retrospective",
            "xp-plan-reviewer",
        ):
            path = agents_dir / f"{name}.md"
            self.assertTrue(path.is_file(), f"Missing: {path}")
            content = path.read_text()
            self.assertGreater(len(content), 500, f"{name} too short")
            self.assertTrue(content.startswith("---"), f"{name} missing frontmatter")


if __name__ == "__main__":
    unittest.main()
