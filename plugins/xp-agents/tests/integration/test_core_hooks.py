#!/usr/bin/env python3
"""Integration tests: core hook pipeline.

Tests for PreToolWrite, PreToolBash, PostToolUse, LintCheck, BashPostTool,
UserPromptLog, and SubagentStop hooks.
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


class TestPreToolWriteIntegration(_IntegrationTestCase):
    def test_write_no_delta_injection(self):
        """M5: Write tool no longer injects smm-delta."""
        self._seed_events(
            [
                make_event("question", priority="\U0001f534", content="Blocker?"),
            ]
        )
        result = self._run_script(
            "pre_tool_write.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        # No delta injection — output may be empty or contain only
        # non-delta content (debt, plan gate)
        if result.stdout.strip():
            output = json.loads(result.stdout)
            ctx = output.get("hookSpecificOutput", {}).get("additionalContext", "")
            self.assertNotIn("smm-delta", ctx)
            self.assertNotIn("smm-context", ctx)

    def test_working_on_conflict_blocks(self):
        """Exit 2 + stderr when another agent is working on the same file."""
        from datetime import datetime, timezone

        coord = {
            "other-agent": {
                "working_on": [str(self.tmpdir / "src" / "app.ts")],
                "updated": datetime.now(timezone.utc).isoformat(),
            }
        }
        (self.smm_dir / ".coordination.json").write_text(json.dumps(coord))
        result = self._run_script(
            "pre_tool_write.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("other-agent", result.stderr)

    def test_tdd_nudge_after_multiple_impl_writes(self):
        """Two impl writes without test → TDD reminder in output."""
        self._run_script(
            "pre_tool_write.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        result = self._run_script(
            "pre_tool_write.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/utils.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("TDD", ctx)

    def test_xp_agent_produces_no_output(self):
        self._seed_events(
            [
                make_event("question", priority="\U0001f534", content="Q?"),
            ]
        )
        result = self._run_script(
            "pre_tool_write.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "agent_type": "xp-housekeeping",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


class TestPostToolUseIntegration(_IntegrationTestCase):
    def test_write_creates_status_event(self):
        result = self._run_script(
            "post_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "hello"},
                "tool_response": {"success": True},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)

        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("src/app.ts", statuses[0]["working_on"][0])
        self.assertEqual(statuses[0]["agent_id"], "main")

    def test_conflict_detection_appends_concern(self):
        self._seed_events(
            [
                make_event(
                    "status",
                    agent_id="other",
                    working_on=[str(self.tmpdir / "src" / "app.ts")],
                ),
            ]
        )
        result = self._run_script(
            "post_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/app.ts"},
                "tool_response": {"success": True},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)

        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("overlap" in c["content"].lower() for c in concerns))

    def test_xp_agent_creates_no_events(self):
        result = self._run_script(
            "post_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "tool_response": {"success": True},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
                "agent_type": "xp-housekeeping",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)


class TestLintCheckIntegration(_IntegrationTestCase):
    def test_no_linter_config_nudges_once(self):
        result = self._run_script(
            "lint_check.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.py", "content": "x"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        # Should return nudge via additionalContext (JSON stdout)
        self.assertIn("linter", result.stdout.lower())
        # No question events — nudge only
        events = self._read_events()
        questions = [e for e in events if e.get("type") == "question"]
        self.assertEqual(len(questions), 0)
        self.assertTrue((self.smm_dir / ".lint-warned").exists())

        # Second run — no nudge
        result2 = self._run_script(
            "lint_check.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.py", "content": "x"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result2.returncode, 0)
        self.assertEqual(result2.stdout, "")


class TestBashPostToolIntegration(_IntegrationTestCase):
    def test_git_commit_creates_commit_event(self):
        (self.tmpdir / "feature.py").write_text("print('hello')")
        subprocess.run(
            ["git", "add", "feature.py"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "Add feature module"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'Add feature module'"},
                "tool_response": {
                    "stdout": "[main abc123] Add feature module\n 1 file changed"
                },
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

        events = self._read_events()
        commit_events = [e for e in events if e.get("type") == "commit"]
        self.assertEqual(len(commit_events), 1)
        self.assertIn("Add feature module", commit_events[0]["content"])

    def test_test_results_creates_status_and_concern(self):
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m pytest tests/"},
                "tool_response": {"stdout": "===== 3 passed, 2 failed in 1.2s ====="},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)

        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("3 passed" in s["content"] for s in statuses))
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("2 failed" in c["content"] for c in concerns))

    def test_irrelevant_command_creates_nothing(self):
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
                "tool_response": {"stdout": "total 0"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)


class TestUserPromptLogIntegration(_IntegrationTestCase):
    def test_logs_prompt_as_customer_input(self):
        result = self._run_script(
            "user_prompt_log.py", {"session_id": "int-test", "prompt": "hello world"}
        )
        self.assertEqual(result.returncode, 0)
        # No goals → block or nudge output expected
        if result.stdout.strip():
            output = json.loads(result.stdout)
            # First prompt blocks, subsequent nudge via additionalContext
            self.assertIn("goals", json.dumps(output).lower())

        events = self._read_events()
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 1)
        self.assertEqual(ci[0]["content"], "hello world")
        self.assertEqual(ci[0]["agent_id"], "customer")

    def test_no_goal_nudge_when_goals_exist(self):
        """No additionalContext when goals already recorded."""
        self._seed_events([make_event("goal", content="Build an app")])
        result = self._run_script(
            "user_prompt_log.py", {"session_id": "int-test", "prompt": "hello"}
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_truncates_long_prompt(self):
        long = "x" * 15000
        self._run_script(
            "user_prompt_log.py", {"session_id": "int-test", "prompt": long}
        )
        events = self._read_events()
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci[0]["content"]), 10000)

    def test_empty_prompt_skips(self):
        result = self._run_script(
            "user_prompt_log.py", {"session_id": "int-test", "prompt": ""}
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 0)

    def test_xp_agent_skips(self):
        result = self._run_script(
            "user_prompt_log.py",
            {"session_id": "int-test", "prompt": "hi", "agent_type": "xp-nav"},
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)

    def test_invalid_json_exits_zero(self):
        script = self.scripts_dir / "user_prompt_log.py"
        r = subprocess.run(
            ["python3", str(script)],
            input="not json",
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )
        self.assertEqual(r.returncode, 0)


class TestSubagentStopIntegration(_IntegrationTestCase):
    def test_records_minimal_status(self):
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
        )
        self.assertEqual(result.returncode, 0)
        # No longer produces reviewer nudge — output should be empty
        self.assertEqual(result.stdout.strip(), "")

        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("task-1", statuses[0]["content"])
        self.assertEqual(statuses[0]["working_on"], [])

    def test_default_agent_id(self):
        self._run_script(
            "subagent_stop.py",
            {"session_id": "int-test", "last_assistant_message": "Done"},
        )
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertIn("subagent", statuses[0]["content"])
        self.assertEqual(statuses[0]["agent_id"], "subagent")

    def test_conflict_detection_appends_concern(self):
        a = make_event("assumption", content="API is REST")
        d = make_event("discovery", content="Actually GraphQL", references=[a["id"]])
        self._seed_events([a, d])

        self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
        )
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(any("contradict" in c["content"].lower() for c in concerns))

    def test_xp_agent_skips(self):
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "task-1",
                "agent_type": "xp-reviewer",
                "last_assistant_message": "Done",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)

    def test_missing_last_message(self):
        result = self._run_script(
            "subagent_stop.py",
            {"session_id": "int-test", "agent_id": "task-1"},
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertEqual(len(statuses), 1)

    def test_invalid_json_exits_zero(self):
        script = self.scripts_dir / "subagent_stop.py"
        r = subprocess.run(
            ["python3", str(script)],
            input="not json",
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
