#!/usr/bin/env python3
"""Integration tests: complex scenarios and round trips.

Tests for session round trips, retrospective, new event types,
full session lifecycle, plan review flow, and three-session accumulation.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase, make_event


class TestSessionRoundTripIntegration(_IntegrationTestCase):
    def test_start_write_end_captures_full_session(self):
        """SessionStart → PostToolUse(Write) → SessionEnd.

        Verifies the full hook chain produces coherent state:
        - session_start returns SMM context
        - post_tool_use appends status with working_on
        - session_end captures that working_on and marks final_status_recorded
        """
        # 1. Session start
        r1 = self._run_script(
            "session_start.py",
            {
                "session_id": "round-trip",
                "source": "startup",
            },
        )
        self.assertEqual(r1.returncode, 0)

        # 2. Post tool use (Write)
        r2 = self._run_script(
            "post_tool_use.py",
            {
                "session_id": "round-trip",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/feature.ts", "content": "code"},
                "tool_response": {"success": True},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(r2.returncode, 0)

        # 3. Session end
        r3 = self._run_script(
            "session_end.py",
            {
                "session_id": "round-trip",
                "reason": "task_complete",
            },
        )
        self.assertEqual(r3.returncode, 0)

        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        se = [e for e in events if e.get("type") == "session_end"]
        self.assertEqual(len(statuses), 1)
        self.assertEqual(len(se), 1)

        self.assertIn("src/feature.ts", se[0]["working_on"][0])
        self.assertTrue(se[0]["final_status_recorded"])
        self.assertIn("task_complete", se[0]["content"])

    def test_prompt_subagent_roundtrip(self):
        """UserPromptSubmit → SubagentStart → SubagentStop → SessionEnd.

        Verifies the full M3.4 hooks integrate with existing lifecycle:
        - user_prompt_log records customer_input
        - subagent_start injects SMM and creates watermark
        - subagent_stop records completion status
        - session_end captures final state
        """
        # 1. User prompt
        r1 = self._run_script(
            "user_prompt_log.py",
            {"session_id": "round-trip-2", "prompt": "Please refactor auth"},
        )
        self.assertEqual(r1.returncode, 0)

        # 2. Subagent start (needs curated SMM file for context injection)
        (self.smm_dir / "SHARED_MENTAL_MODEL.md").write_text(
            "# Shared Mental Model\n## Intent\n- Refactor auth\n"
        )
        r2 = self._run_script(
            "subagent_start.py",
            {"session_id": "round-trip-2", "agent_id": "task-1"},
        )
        self.assertEqual(r2.returncode, 0)
        output = json.loads(r2.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Shared Mental Model", ctx)

        # 3. Subagent stop
        r3 = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "round-trip-2",
                "agent_id": "task-1",
                "last_assistant_message": "Refactored auth module",
            },
        )
        self.assertEqual(r3.returncode, 0)

        # 4. Session end
        r4 = self._run_script(
            "session_end.py",
            {"session_id": "round-trip-2", "reason": "done"},
        )
        self.assertEqual(r4.returncode, 0)

        # Verify full event chain
        events = self._read_events()
        types = [e["type"] for e in events]
        self.assertIn("customer_input", types)
        self.assertIn("status", types)
        self.assertIn("session_end", types)

        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(ci[0]["content"], "Please refactor auth")
        self.assertEqual(ci[0]["agent_id"], "customer")

        statuses = [e for e in events if e.get("type") == "status"]
        task_status = [s for s in statuses if s.get("agent_id") == "task-1"]
        self.assertTrue(len(task_status) >= 1)
        self.assertIn("task-1", task_status[0]["content"])


class TestRetrospectiveIntegration(_IntegrationTestCase):
    def test_sufficient_events_writes_retro_input(self):
        """≥5 events → .retro-input.json written, exit 0, context in stdout."""
        self._seed_events([make_event(content=f"e{i}") for i in range(6)])
        result = self._run_script(
            "retrospective.py",
            {
                "session_id": "int-test",
                "source": "startup",
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("6", ctx)
        self.assertTrue((self.smm_dir / ".retro-input.json").exists())
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(data["unanalyzed_count"], 6)

    def test_insufficient_events_no_output(self):
        """<5 events → no output, no file, exit 0."""
        self._seed_events([make_event(content=f"e{i}") for i in range(3)])
        result = self._run_script(
            "retrospective.py",
            {
                "session_id": "int-test",
                "source": "startup",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_xp_agent_no_output(self):
        """xp- agents → exit 0, no output."""
        self._seed_events([make_event(content=f"e{i}") for i in range(10)])
        result = self._run_script(
            "retrospective.py",
            {
                "session_id": "int-test",
                "source": "startup",
                "agent_type": "xp-test",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_compact_source_no_output(self):
        """compact source → exit 0, no output."""
        self._seed_events([make_event(content=f"e{i}") for i in range(10)])
        result = self._run_script(
            "retrospective.py",
            {
                "session_id": "int-test",
                "source": "compact",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_retro_input_includes_history(self):
        """Previous retro files included in .retro-input.json."""
        retro_dir = self.smm_dir / "retrospectives"
        retro_data = {"keep": [{"content": "good TDD"}], "fix": [], "try": []}
        (retro_dir / "2026-03-10T00-00-00.json").write_text(json.dumps(retro_data))

        self._seed_events([make_event(content=f"e{i}") for i in range(6)])
        result = self._run_script(
            "retrospective.py",
            {
                "session_id": "int-test",
                "source": "startup",
            },
        )
        self.assertEqual(result.returncode, 0)
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertEqual(len(data["previous_retros"]), 1)


class TestNewEventTypesIntegration(_IntegrationTestCase):
    def _run_append(self, *args: str) -> subprocess.CompletedProcess:
        """Run append.sh with given args in the temp git repo."""
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(Path(__file__).parent.parent.parent)
        append_sh = Path(__file__).parent.parent.parent / "smm" / "append.sh"
        return subprocess.run(
            ["bash", str(append_sh), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.tmpdir),
        )

    def test_append_goal_and_curation_data(self):
        """Goal event appears in curation data under intent."""
        r = self._run_append(
            "--type", "goal", "--agent", "main", "--content", "Ship v2.0"
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "goal")

        import materialize as mat

        data = mat.prepare_curation_data(self.smm_dir)
        intent_contents = [i["content"] for i in data["current_smm"]["intent"]]
        self.assertIn("Ship v2.0", intent_contents)

    def test_append_debt_and_curation_data(self):
        """Debt event appears in curation data under risks."""
        r = self._run_append(
            "--type",
            "debt",
            "--agent",
            "main",
            "--content",
            "Legacy auth module",
            "--files",
            '["src/auth.py", "src/legacy.py"]',
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "debt")
        self.assertEqual(events[0]["files"], ["src/auth.py", "src/legacy.py"])

        import materialize as mat

        data = mat.prepare_curation_data(self.smm_dir)
        risk_contents = [r["content"] for r in data["current_smm"]["risks"]]
        self.assertIn("Legacy auth module", risk_contents)

    def test_append_customer_intent_and_curation_data(self):
        """Customer intent event appears in curation data under intent."""
        r = self._run_append(
            "--type",
            "customer_intent",
            "--agent",
            "main",
            "--content",
            "Need OAuth integration",
            "--intent-status",
            "open",
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "customer_intent")
        self.assertEqual(events[0]["intent_status"], "open")

        import materialize as mat

        data = mat.prepare_curation_data(self.smm_dir)
        intent_contents = [i["content"] for i in data["current_smm"]["intent"]]
        self.assertIn("Need OAuth integration", intent_contents)

    def test_retro_includes_session_stats(self):
        """Retrospective .retro-input.json includes session_stats."""
        self._seed_events([make_event(content=f"e{i}") for i in range(6)])
        result = self._run_script(
            "retrospective.py",
            {"session_id": "int-test", "source": "startup"},
        )
        self.assertEqual(result.returncode, 0)
        with open(self.smm_dir / ".retro-input.json") as f:
            data = json.load(f)
        self.assertIn("session_stats", data)
        self.assertIn("status_count", data["session_stats"])
        self.assertIn("concerns_raised", data["session_stats"])


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
        self.assertIn("Resume immediately", ctx)
        self.assertIn("smm-protocol", ctx)
        # Marker written
        self.assertTrue((self.smm_dir / ".needs-session-review").exists())

        # Clear marker so pre_tool_write doesn't block
        (self.smm_dir / ".needs-session-review").unlink()

        # 2. Pre tool write (Write) — no navigator nudge
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
        if r2.stdout.strip():
            output2 = json.loads(r2.stdout)
            ctx2 = output2["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("xp-navigator", ctx2)

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
    """M7: Plan subagent → block, regular subagent → nudge."""

    def test_plan_subagent_blocks_with_reviewer(self):
        """Plan agent_type → decision:block with xp-plan-reviewer instruction."""
        # Seed decisions so plan review has context
        self._seed_events(
            [
                make_event(
                    "decision",
                    content="Use REST API",
                    topic="api",
                    metadata={"draft": False},
                ),
                make_event(
                    "convention",
                    content="TDD for all features",
                    topic="testing",
                ),
            ]
        )
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
        self.assertEqual(result.stdout.strip(), "")
        events = self._read_events()
        gate = [e for e in events if "plan_awaiting_review" in e.get("content", "")]
        self.assertEqual(len(gate), 1)

    def test_regular_subagent_nudges_reviewer(self):
        """Non-Plan subagent → decision:approve with xp-subagent-reviewer nudge."""
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "m7-plan",
                "agent_id": "task-2",
                "last_assistant_message": "Completed the refactoring",
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertEqual(output["decision"], "approve")
        self.assertIn("xp-subagent-reviewer", output["reason"])

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
            "xp-retrospective",
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
            data3["previous_retros"][0]["keep"][0]["content"],
            "Good TDD practice",
        )


if __name__ == "__main__":
    unittest.main()
