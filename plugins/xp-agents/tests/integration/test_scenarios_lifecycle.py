#!/usr/bin/env python3
"""Integration tests: full session lifecycle, plan review, multi-session.

Split from test_scenarios.py — covers TestFullSessionLifecycle,
TestPlanReviewFlow, TestThreeSessionAccumulation.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, make_event


class TestFullSessionLifecycle(_IntegrationTestCase):
    """M7: Chain session_start → pre_tool_write → post_tool_use → session_end."""

    def test_full_lifecycle_first_run(self):
        """Empty SMM → full lifecycle produces correct event chain."""
        # 1. Session start (first run — empty SMM)
        r1 = self._run_script(
            "session_start.py",
            {"session_id": "m7-lifecycle", "source": "startup"},
        )
        self.assertEqual(r1.returncode, 0)
        output = json.loads(r1.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        # Should have GUPP + skills (no SMM, no nudges)
        self.assertIn("xp-kickoff", ctx)
        # Marker written
        self.assertTrue((self.smm_dir / ".needs-kickoff").exists())

        # Clear marker so pre_tool_write doesn't block
        (self.smm_dir / ".needs-kickoff").unlink()

        # 2. Pre tool write (Write)
        r2 = self._run_script(
            "pre_tool_write.py",
            {
                "session_id": "m7-lifecycle",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/feature.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(r2.returncode, 0)

        # 3. Post tool use (Write) — status event recorded
        r3 = self._run_script(
            "post_tool_use.py",
            {
                "session_id": "m7-lifecycle",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/feature.ts", "content": "code"},
                "tool_response": {"success": True},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(r3.returncode, 0)

        # 4. Session end
        r4 = self._run_script(
            "session_end.py",
            {"session_id": "m7-lifecycle", "reason": "task_complete"},
        )
        self.assertEqual(r4.returncode, 0)

        # Verify accumulated events
        events = self._read_events()
        types = [e["type"] for e in events]
        self.assertIn("status", types)
        self.assertIn("session_end", types)

        # session_end should capture working_on from the status event
        se = next(e for e in events if e["type"] == "session_end")
        self.assertTrue(
            any("src/feature.ts" in w for w in se["working_on"]),
            f"working_on should include feature.ts: {se['working_on']}",
        )
        self.assertIn("task_complete", se["content"])
        self.assertEqual(se["event_count"], len(events) - 1)  # excludes itself


class TestPlanReviewFlow(_IntegrationTestCase):
    """Both plan flows (ExitPlanMode tool + Plan subagent) nudge plan review."""

    def test_exit_plan_mode_nudges_review(self):
        """ExitPlanMode tool → additionalContext nudges /xp-review-plan."""
        # Seed decisions so plan review has context
        self._seed_events(
            [
                make_event(
                    "decision",
                    content="Use REST API",
                    topic="api",
                ),
                make_event(
                    "convention",
                    content="TDD for all features",
                    topic="testing",
                ),
            ]
        )
        result = self._run_script(
            "post_tool_exit_plan.py",
            {
                "session_id": "m7-plan",
                "agent_id": "main",
                "tool_name": "ExitPlanMode",
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertIn(
            "xp-review-plan", output["hookSpecificOutput"]["additionalContext"]
        )
        events = self._read_events()
        gate = [e for e in events if "plan_awaiting_review" in e.get("content", "")]
        self.assertEqual(len(gate), 1)

    def test_plan_subagent_writes_gate(self):
        """Plan subagent (via Agent tool) → writes gate marker and event."""
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "m7-plan",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "1. Add endpoint\n2. Write tests",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        gate = [e for e in events if "plan_awaiting_review" in e.get("content", "")]
        self.assertEqual(len(gate), 1)
        marker = self.smm_dir / ".plan-awaiting-review"
        self.assertTrue(marker.exists())

    def test_regular_subagent_no_reviewer_nudge(self):
        """Non-Plan subagent → no reviewer nudge (xp-subagent-reviewer removed)."""
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "m7-plan",
                "agent_id": "task-2",
                "last_assistant_message": "Completed the refactoring",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

        # Should also have recorded a status event
        events = self._read_events()
        statuses = [e for e in events if e["type"] == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertIn("task-2", statuses[0]["content"])


class TestThreeSessionAccumulation(_IntegrationTestCase):
    """M7: Retro data accumulates across sessions."""

    def test_cross_session_retro_trends(self):
        """Session 1 → end, Session 2 → retro, Session 3 → retro sees history."""
        # --- Session 1: seed events, run session_end ---
        self._seed_events([make_event(content=f"s1-e{i}") for i in range(6)])
        self._run_script(
            "session_end.py",
            {"session_id": "s1", "reason": "done"},
        )

        # --- Session 2: retrospective sees 7 unanalyzed events ---
        r2 = self._run_script(
            "retrospective.py",
            {"session_id": "s2", "source": "startup"},
        )
        self.assertEqual(r2.returncode, 0)
        retro_input_path = self.smm_dir / ".retro-input.json"
        self.assertTrue(retro_input_path.exists())
        with open(retro_input_path) as f:
            data = json.load(f)
        self.assertGreaterEqual(data["unanalyzed_count"], 6)
        ctx2 = json.loads(r2.stdout)
        self.assertIn(
            "xp-kickoff",
            ctx2["hookSpecificOutput"]["additionalContext"],
        )

        # Simulate retro agent writing a retrospective file
        retro_dir = self.smm_dir / "retrospectives"
        retro_dir.mkdir(exist_ok=True)
        retro_data = {
            "keep": [{"content": "Good TDD practice"}],
            "fix": [{"content": "Slow CI"}],
            "try": [{"content": "Pair more"}],
        }
        (retro_dir / "2026-03-14T00-00-00.json").write_text(json.dumps(retro_data))

        # Mark retro as done + add session 2 work events
        events = self._read_events()
        events.append(make_event("retrospective", content="Retrospective complete"))
        for i in range(6):
            events.append(make_event(content=f"s2-e{i}"))
        self._seed_events(events)

        # Run session_end for session 2
        self._run_script(
            "session_end.py",
            {"session_id": "s2", "reason": "done"},
        )

        # --- Session 3: retro sees previous retro in history ---
        r3 = self._run_script(
            "retrospective.py",
            {"session_id": "s3", "source": "startup"},
        )
        self.assertEqual(r3.returncode, 0)
        self.assertTrue(retro_input_path.exists())
        with open(retro_input_path) as f:
            data3 = json.load(f)
        self.assertEqual(len(data3["previous_retros"]), 1)
        self.assertEqual(
            data3["previous_retros"][0]["keep"][0],
            "Good TDD practice",
        )


# ===========================================================================
# M10: Sprint-aware SubagentStart + compact reinjection
# ===========================================================================


class TestSprintTieredInjection(_IntegrationTestCase):
    """M10: SubagentStart injects sprint context by agent type."""

    _SPRINT_MD = (
        "# Sprint: Build API\n\n"
        "- **Sprint ID:** sprint-001\n\n"
        "## Stories\n\n"
        "### story-001: Registration\n"
        "- **Status:** done\n"
    )

    def _write_sprint_and_smm(self):
        from conftest import write_smm_fixture

        write_smm_fixture(
            self.smm_dir,
            intent=[("Ship v1", "goal")],
            constraints=[("TDD", "convention")],
            wisdom=["Commit often"],
        )
        sprint_file = self.smm_dir / "sprint.json"
        sprint_file.write_text(self._SPRINT_MD)

    def test_plan_reviewer_gets_values_subprocess(self):
        """SubagentStart subprocess: plan reviewer gets XP values."""
        self._write_sprint_and_smm()
        result = self._run_script(
            "subagent_start.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-rev-1",
                "agent_type": "xp-plan-reviewer",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("XP Values", result.stdout)

    def test_compact_reinjects_smm_not_sprint(self):
        """SessionStart compact reinjects SMM but not sprint.json."""
        self._write_sprint_and_smm()
        self._seed_events([make_event()])
        result = self._run_script(
            "session_start.py",
            {"session_id": "int-test", "source": "compact"},
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Ship v1", ctx)  # SMM content
        self.assertNotIn("sprint-001", ctx)  # sprint.json not injected


# ===========================================================================
# sprint_retro_detection.py — detection + file I/O
# ===========================================================================


class TestSprintRetroDetectionIntegration(_IntegrationTestCase):
    """Integration test for sprint retro detection with real file I/O."""

    def test_detects_dangling_sprint_end(self):
        """Sprint end without retro_done → creates .sprint-retro-input.json."""
        from conftest import SPRINT_COMPLETE_WITH_ID
        from event_schema import SPRINT_ACTION_END

        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)

        self._seed_events(
            [
                make_event("status", content="Working"),
                make_event(
                    "sprint",
                    content="Sprint complete",
                    metadata={
                        "action": SPRINT_ACTION_END,
                        "sprint_id": "sprint-001",
                    },
                ),
            ]
        )
        (self.smm_dir / ".retro-input.json").write_text("{}")

        import sprint_retro_detection

        events = self._read_events()
        result = sprint_retro_detection.maybe_run_sprint_retro_branch(
            self.smm_dir, events
        )

        self.assertIsNotNone(result)
        self.assertIn("sprint-001", result)
        self.assertTrue((self.smm_dir / ".sprint-retro-input.json").exists())
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_no_detection_when_retro_done(self):
        """Sprint end followed by retro_done → no detection."""
        from event_schema import (
            SPRINT_ACTION_END,
            STATUS_ACTION_SPRINT_RETRO_DONE,
        )

        self._seed_events(
            [
                make_event(
                    "sprint",
                    content="Sprint complete",
                    metadata={
                        "action": SPRINT_ACTION_END,
                        "sprint_id": "sprint-001",
                    },
                ),
                make_event(
                    "status",
                    content="Sprint retro done",
                    metadata={
                        "action": STATUS_ACTION_SPRINT_RETRO_DONE,
                        "sprint_id": "sprint-001",
                    },
                ),
            ]
        )

        import sprint_retro_detection

        events = self._read_events()
        result = sprint_retro_detection.maybe_run_sprint_retro_branch(
            self.smm_dir, events
        )
        self.assertIsNone(result)


# ===========================================================================
# prepare_sprint_retro_data.py — CLI subprocess
# ===========================================================================


class TestPrepareSprintRetroDataIntegration(_IntegrationTestCase):
    """Subprocess tests for prepare_sprint_retro_data.py CLI."""

    def test_writes_sprint_retro_input(self):
        from conftest import SPRINT_COMPLETE_WITH_ID

        (self.smm_dir / "sprint.json").write_text(SPRINT_COMPLETE_WITH_ID)

        # Create a session retro in the sprint period
        retro_dir = self.smm_dir / "retrospectives"
        retro_dir.mkdir(exist_ok=True)
        (retro_dir / "2026-04-02T10-00-00.json").write_text(
            json.dumps(
                {
                    "timestamp": "2026-04-02T10:00:00+00:00",
                    "keep": [{"content": "Good TDD"}],
                    "fix": [],
                    "try": [],
                }
            )
        )

        result = subprocess.run(
            [
                "python3",
                str(self.scripts_dir / "prepare_sprint_retro_data.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RETRO_INPUT=", result.stdout)

        retro_input = json.loads(
            (self.smm_dir / ".sprint-retro-input.json").read_text()
        )
        self.assertEqual(retro_input["sprint_id"], "sprint-001")
        self.assertEqual(len(retro_input["session_retros"]), 1)
        self.assertIn("velocity", retro_input)

    def test_missing_sprint_exits_gracefully(self):
        result = subprocess.run(
            [
                "python3",
                str(self.scripts_dir / "prepare_sprint_retro_data.py"),
                "--smm-dir",
                str(self.smm_dir),
            ],
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._test_env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("No sprint data", result.stderr)


if __name__ == "__main__":
    unittest.main()
