#!/usr/bin/env python3
"""Integration tests: session round trips, retrospective, new event types.

Full lifecycle, plan review, and multi-session tests in test_scenarios_lifecycle.py.
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
        env = self._test_env.copy()
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
        """Goal event is recorded in the event log (current_smm stays empty
        until housekeeper merges it)."""
        r = self._run_append(
            "--type", "goal", "--agent", "main", "--content", "Ship v2.0"
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "goal")

        import materialize as mat

        data = mat.prepare_curation_data(self.smm_dir)
        # current_smm is sourced from shared_mental_model.json, not events.
        # An appended goal event does NOT automatically promote into
        # current_smm until the housekeeper merges it.
        self.assertEqual(data["health"]["intent_count"], 0)
        self.assertEqual(data["current_smm"]["intent"], [])

    def test_append_debt_and_curation_data(self):
        """Debt event appears in new_since_last_curation.debt for housekeeper."""
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
        debt_contents = [d["content"] for d in data["new_since_last_curation"]["debt"]]
        self.assertIn("Legacy auth module", debt_contents)

    def test_append_customer_intent_and_curation_data(self):
        """Customer intent event recorded (current_smm empty until curated)."""
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
        self.assertEqual(data["health"]["intent_count"], 0)
        self.assertEqual(data["current_smm"]["intent"], [])

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


# ===========================================================================
# save_retrospective.py — subprocess integration
# ===========================================================================


class TestSaveRetrospectiveIntegration(_IntegrationTestCase):
    """Subprocess tests for save_retrospective.py CLI."""

    _SCRIPT = "save_retrospective.py"

    def _run_save_retro(self, kft_json: str, extra_args: list[str] | None = None):
        cmd = [
            "python3",
            str(self.scripts_dir / self._SCRIPT),
            "--smm-dir",
            str(self.smm_dir),
        ]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(
            cmd,
            input=kft_json,
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=self._test_env,
        )

    def test_session_retro_writes_event_and_file(self):
        kft = {
            "keep": [{"content": "TDD discipline"}],
            "fix": [{"content": "Slow CI"}],
            "try": [{"content": "Pair more"}],
        }
        result = self._run_save_retro(json.dumps(kft))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("EVENT_ID=", result.stdout)
        self.assertIn("RETRO_FILE=", result.stdout)

        events = self._read_events()
        retros = [e for e in events if e.get("type") == "retrospective"]
        self.assertEqual(len(retros), 1)
        self.assertIn("1 keeps, 1 fixes, 1 tries", retros[0]["content"])

        retro_dir = self.smm_dir / "retrospectives"
        retro_files = list(retro_dir.glob("*.json"))
        self.assertEqual(len(retro_files), 1)

    def test_sprint_retro_kind(self):
        kft = {"keep": [], "fix": [], "try": []}
        result = self._run_save_retro(json.dumps(kft), ["--retro-kind", "sprint"])
        self.assertEqual(result.returncode, 0, result.stderr)

        events = self._read_events()
        retro = next(e for e in events if e["type"] == "retrospective")
        self.assertEqual(retro.get("metadata", {}).get("action"), "sprint_retro_done")

    def test_cleans_up_input_file(self):
        (self.smm_dir / ".retro-input.json").write_text("{}")
        kft = {"keep": [], "fix": [], "try": []}
        result = self._run_save_retro(json.dumps(kft))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.smm_dir / ".retro-input.json").exists())

    def test_invalid_input_exits_1(self):
        result = self._run_save_retro("not json at all")
        self.assertEqual(result.returncode, 1)


# ===========================================================================
# session_end_warning.py — Stop hook integration
# ===========================================================================


class TestSessionEndWarningIntegration(_IntegrationTestCase):
    """Subprocess tests for session_end_warning.py Stop hook."""

    def test_returns_warning_with_unresolved_concerns(self):
        self._seed_events(
            [
                make_event("concern", content="Flaky test", severity="medium"),
            ]
        )
        result = self._run_script(
            "session_end_warning.py",
            {"session_id": "t", "agent_id": "main"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("unresolved concern", result.stdout)

    def test_returns_summary_nudge_without_concerns(self):
        self._seed_events(
            [
                make_event("status", content="Working on auth"),
            ]
        )
        result = self._run_script(
            "session_end_warning.py",
            {"session_id": "t", "agent_id": "main"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("Summarize", result.stdout)

    def test_xp_agent_skips(self):
        self._seed_events(
            [
                make_event("concern", content="Bug", severity="high"),
            ]
        )
        result = self._run_script(
            "session_end_warning.py",
            {"session_id": "t", "agent_id": "main", "agent_type": "xp-nav"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
