#!/usr/bin/env python3
"""Integration tests: full subprocess pipeline for all hook scripts.

Each test creates a temp git repo, inits SMM via init.sh, pipes JSON to a
hook script as a subprocess, and verifies side effects on disk (events,
backups, watermarks) and stdout/stderr/exit codes.

Slower than unit tests (~5s) due to subprocess + git repo setup.
Run with: python3 -m unittest scripts/test_integration.py -v

Frequency: pre-push (not pre-commit — too slow for every commit).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Allow importing from sibling directories
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smm"))

from test_engine import make_event

# ===========================================================================
# Base class
# ===========================================================================


class _IntegrationTestCase(unittest.TestCase):
    """Base class that creates a temp git repo and inits SMM via init.sh."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # Create a git repo
        subprocess.run(
            ["git", "init"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        # Need an initial commit so HEAD exists
        (self.tmpdir / "README").write_text("init")
        subprocess.run(
            ["git", "add", "README"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=self.tmpdir,
            capture_output=True,
            check=True,
        )

        # Init SMM
        init_sh = Path(__file__).parent.parent / "smm" / "init.sh"
        result = subprocess.run(
            ["bash", str(init_sh)],
            cwd=self.tmpdir,
            capture_output=True,
            text=True,
            check=True,
        )
        self.smm_dir = Path(result.stdout.strip())
        self.scripts_dir = Path(__file__).parent

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        # Clean up SMM dir (under ~/.claude/xp-agents/<hash>)
        smm_parent = self.smm_dir.parent
        if smm_parent.exists():
            shutil.rmtree(smm_parent)

    def _run_script(
        self, script_name: str, input_data: dict
    ) -> subprocess.CompletedProcess:
        """Run a hook script as a subprocess with JSON on stdin."""
        return subprocess.run(
            ["python3", str(self.scripts_dir / script_name)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )

    def _read_events(self) -> list[dict]:
        """Read events from the SMM events.jsonl."""
        events_file = self.smm_dir / "events.jsonl"
        if not events_file.exists():
            return []
        events = []
        for line in events_file.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def _seed_events(self, events: list[dict]) -> None:
        """Write seed events to events.jsonl."""
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        (self.smm_dir / "events.jsonl").write_text(
            "\n".join(lines) + ("\n" if lines else "")
        )


# ===========================================================================
# Session lifecycle (Milestone 3.1)
# ===========================================================================


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
                "agent_type": "xp-navigator",
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
                "agent_type": "xp-navigator",
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
        """stdin → subagent_start.py → stdout + watermark on disk."""
        self._seed_events([make_event(), make_event()])
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

        wm_file = self.smm_dir / ".watermark-explorer-1"
        self.assertTrue(wm_file.exists())
        self.assertEqual(wm_file.read_text(), "2")

    def test_xp_agent_produces_no_output(self):
        self._seed_events([make_event()])
        result = self._run_script(
            "subagent_start.py",
            {
                "session_id": "int-test",
                "agent_id": "explorer-1",
                "agent_type": "xp-navigator",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        wm_file = self.smm_dir / ".watermark-explorer-1"
        self.assertFalse(wm_file.exists())


# ===========================================================================
# PreToolUse (Milestone 3.2)
# ===========================================================================


class TestPreToolUseIntegration(_IntegrationTestCase):
    def test_write_injects_delta(self):
        """stdin → pre_tool_use.py → stdout with delta containing events."""
        self._seed_events(
            [
                make_event("question", priority="\U0001f534", content="Blocker?"),
            ]
        )
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("smm-delta", ctx)
        self.assertIn("Blocker?", ctx)

    def test_working_on_conflict_blocks(self):
        """Exit 2 + stderr when another agent is working on the same file."""
        self._seed_events(
            [
                make_event(
                    "status",
                    agent_id="other-agent",
                    working_on=[
                        str(self.tmpdir / "src" / "app.ts"),
                    ],
                ),
            ]
        )
        result = self._run_script(
            "pre_tool_use.py",
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

    def test_read_tool_no_output_for_non_red(self):
        """Red-only tier filters out status events → no output."""
        self._seed_events([make_event("status", content="busy")])
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Read",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_tdd_nudge_after_multiple_impl_writes(self):
        """Two impl writes without test → TDD reminder in output."""
        self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        result = self._run_script(
            "pre_tool_use.py",
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
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts"},
                "agent_id": "main",
                "agent_type": "xp-navigator",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


# ===========================================================================
# PostToolUse (Milestone 3.3)
# ===========================================================================


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
        self.assertEqual(result.stdout, "")

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
                "agent_type": "xp-navigator",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)


class TestLintCheckIntegration(_IntegrationTestCase):
    def test_no_linter_config_warns_once(self):
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
        self.assertEqual(result.stdout, "")

        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("linter", concerns[0]["content"].lower())
        self.assertTrue((self.smm_dir / ".lint-warned").exists())

        # Second run — no new concern
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
        events2 = self._read_events()
        concerns2 = [e for e in events2 if e.get("type") == "concern"]
        self.assertEqual(len(concerns2), 1)


class TestBashPostToolIntegration(_IntegrationTestCase):
    def test_git_commit_creates_decision(self):
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
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].get("metadata", {}).get("draft"))
        self.assertIn("Add feature module", decisions[0]["content"])

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


# ===========================================================================
# Customer & Subagent Tracking (Milestone 3.4)
# ===========================================================================


class TestUserPromptLogIntegration(_IntegrationTestCase):
    def test_logs_prompt_as_customer_input(self):
        result = self._run_script(
            "user_prompt_log.py", {"session_id": "int-test", "prompt": "hello world"}
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

        events = self._read_events()
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 1)
        self.assertEqual(ci[0]["content"], "hello world")
        self.assertEqual(ci[0]["agent_id"], "customer")

    def test_truncates_long_prompt(self):
        long = "x" * 15000
        self._run_script(
            "user_prompt_log.py", {"session_id": "int-test", "prompt": long}
        )
        events = self._read_events()
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci[0]["content"]), 10000)

    def test_empty_prompt_still_logs(self):
        result = self._run_script(
            "user_prompt_log.py", {"session_id": "int-test", "prompt": ""}
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        ci = [e for e in events if e.get("type") == "customer_input"]
        self.assertEqual(len(ci), 1)

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
        self.assertEqual(result.stdout, "")

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


# ===========================================================================
# Round-trip: full session lifecycle
# ===========================================================================


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

        # 2. Subagent start
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


# ===========================================================================
# Plan Review (Milestone 4)
# ===========================================================================


class TestPlanReviewIntegration(_IntegrationTestCase):
    def test_large_plan_returns_context(self):
        """Large plan → stdout with hookSpecificOutput containing flags."""
        plan = "\n".join(f"{i + 1}. Step {i + 1}" for i in range(15))
        result = self._run_script(
            "plan_review.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-1",
                "last_assistant_message": plan,
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("15 steps", ctx)
        self.assertIn("large plan", ctx.lower())

    def test_xp_agent_no_output(self):
        """xp- agent_type → no stdout, no events."""
        result = self._run_script(
            "plan_review.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-1",
                "agent_type": "xp-plan-reviewer",
                "last_assistant_message": "1. Do stuff",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        events = self._read_events()
        self.assertEqual(len(events), 0)

    def test_plan_review_appends_event(self):
        """plan_review.py appends a status event to the SMM."""
        result = self._run_script(
            "plan_review.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-1",
                "last_assistant_message": "1. Write tests\n2. Implement feature",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("plan review" in s["content"].lower() for s in statuses))

    def test_small_plan_with_tests_clean(self):
        """Small plan with test keywords → context but no flags."""
        result = self._run_script(
            "plan_review.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-1",
                "last_assistant_message": (
                    "1. Write unit tests\n2. Implement auth\n3. Run tests"
                ),
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertNotIn("No test/TDD strategy", ctx)
        self.assertNotIn("large plan", ctx.lower())

    def test_missing_message_no_output(self):
        """No last_assistant_message → no output."""
        result = self._run_script(
            "plan_review.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-1",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


# ===========================================================================
# Retrospective (Milestone 5)
# ===========================================================================


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


# ===========================================================================
# New event types: goal, debt, customer_intent (Milestone 5.2)
# ===========================================================================


class TestNewEventTypesIntegration(_IntegrationTestCase):
    def _run_append(self, *args: str) -> subprocess.CompletedProcess:
        """Run append.sh with given args in the temp git repo."""
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(Path(__file__).parent.parent)
        append_sh = Path(__file__).parent.parent / "smm" / "append.sh"
        return subprocess.run(
            ["bash", str(append_sh), *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.tmpdir),
        )

    def test_append_goal_and_materialize(self):
        """Goal event appears in materialized view under Project Goals."""
        r = self._run_append(
            "--type", "goal", "--agent", "main", "--content", "Ship v2.0"
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        events = self._read_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "goal")

        # Materialize and check
        import materialize as mat

        md = mat.materialize(self.smm_dir)
        self.assertIn("## Project Goals", md)
        self.assertIn("🎯", md)
        self.assertIn("Ship v2.0", md)

    def test_append_debt_and_materialize(self):
        """Debt event appears in materialized view under Technical Debt."""
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

        md = mat.materialize(self.smm_dir)
        self.assertIn("## Technical Debt", md)
        self.assertIn("Legacy auth module", md)
        self.assertIn("src/auth.py", md)

    def test_append_customer_intent_and_materialize(self):
        """Customer intent event appears in materialized view."""
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

        md = mat.materialize(self.smm_dir)
        self.assertIn("## Customer Intent", md)
        self.assertIn("📋", md)
        self.assertIn("Need OAuth integration", md)

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
        self.assertIn("pair_guidance_count", data["session_stats"])
        self.assertIn("status_count", data["session_stats"])
        self.assertIn("concerns_raised", data["session_stats"])


if __name__ == "__main__":
    unittest.main()
