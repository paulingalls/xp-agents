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

    def _run_script_with_env(
        self, script_name: str, input_data: dict, env_overrides: dict
    ) -> subprocess.CompletedProcess:
        """Run a hook script with custom environment variables."""
        env = os.environ.copy()
        env.update(env_overrides)
        return subprocess.run(
            ["python3", str(self.scripts_dir / script_name)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
            env=env,
        )

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
        # Now produces hookSpecificOutput with quality reviewer nudge
        if result.stdout.strip():
            output = json.loads(result.stdout)
            ctx = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("xp-quality-reviewer", ctx)

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
        # Now produces hookSpecificOutput with reviewer nudge
        if result.stdout.strip():
            output = json.loads(result.stdout)
            ctx = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("xp-subagent-reviewer", ctx)

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


# ===========================================================================
# Simplify Gate (Milestone 5.4)
# ===========================================================================


class TestSimplifyGateIntegration(_IntegrationTestCase):
    def test_file_changes_blocks_stop(self):
        """customer_input + status with working_on → exit 2 with /simplify."""
        self._seed_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        result = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("/simplify", result.stderr)

    def test_no_changes_allows_stop(self):
        """customer_input only, no file changes → exit 0, no output."""
        self._seed_events([make_event("customer_input", content="just chatting")])
        result = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_xp_agent_allows_stop(self):
        """xp- agent_type → exit 0 even with file changes."""
        self._seed_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/x.ts"]),
            ]
        )
        result = self._run_script(
            "simplify_gate.py",
            {
                "session_id": "int-test",
                "agent_id": "main",
                "agent_type": "xp-nav",
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


# ===========================================================================
# Bash Failure — PostToolUseFailure
# ===========================================================================


class TestBashFailureIntegration(_IntegrationTestCase):
    def test_failed_test_creates_concern(self):
        """Failed pytest → status + concern events on disk."""
        result = self._run_script(
            "bash_failure.py",
            {
                "session_id": "int-test",
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m pytest tests/"},
                "error": "Command exited with non-zero status code 1",
                "is_interrupt": False,
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("pytest", statuses[0]["content"])
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_non_test_command_creates_nothing(self):
        """Non-test Bash failure → no events."""
        result = self._run_script(
            "bash_failure.py",
            {
                "session_id": "int-test",
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "ls /nonexistent"},
                "error": "exit code 2",
                "is_interrupt": False,
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)

    def test_interrupt_creates_nothing(self):
        """User interrupt → no events."""
        result = self._run_script(
            "bash_failure.py",
            {
                "session_id": "int-test",
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "tool_input": {"command": "pytest"},
                "error": "interrupted",
                "is_interrupt": True,
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)


# ===========================================================================
# Lint Check — additional coverage
# ===========================================================================


class TestLintCheckIntegrationExtended(_IntegrationTestCase):
    def test_linter_config_detected_and_run(self):
        """ruff.toml present + ruff on PATH → linter runs on file."""
        (self.tmpdir / "ruff.toml").write_text("[lint]\n")
        # Create a Python file with a lint issue (unused import)
        src = self.tmpdir / "bad.py"
        src.write_text("import os\n")
        result = self._run_script(
            "lint_check.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": str(src), "content": "import os\n"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        # If ruff is installed, we get a concern for unused import.
        # If ruff is not installed, we get nothing (graceful degradation).
        # Either way, no crash and no "no linter" warning.
        no_linter_concerns = [
            e
            for e in events
            if e.get("type") == "concern"
            and "no linter" in e.get("content", "").lower()
        ]
        self.assertEqual(len(no_linter_concerns), 0)

    def test_xp_agent_skips_lint(self):
        """xp- agent_type → exit 0, no events."""
        result = self._run_script(
            "lint_check.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.py", "content": "x"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
                "agent_type": "xp-quality-reviewer",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)

    def test_no_linter_warning_only_once(self):
        """Second run without linter config → no duplicate concern."""
        for _ in range(2):
            self._run_script(
                "lint_check.py",
                {
                    "session_id": "int-test",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "src/app.py", "content": "x"},
                    "cwd": str(self.tmpdir),
                    "agent_id": "main",
                },
            )
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1, "Should warn exactly once")


# ===========================================================================
# Bash PostTool — additional framework coverage
# ===========================================================================


class TestBashPostToolIntegrationExtended(_IntegrationTestCase):
    def test_jest_results_create_events(self):
        """jest output → status + concern events."""
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "npx jest"},
                "tool_response": {"stdout": "Tests:  1 failed, 4 passed, 5 total"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("4 passed" in s["content"] for s in statuses))
        self.assertTrue(len(concerns) >= 1)

    def test_go_test_results_create_events(self):
        """go test output → status event."""
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "go test ./..."},
                "tool_response": {
                    "stdout": (
                        "ok  \tgithub.com/user/pkg\t0.3s\n"
                        "ok  \tgithub.com/user/lib\t0.1s"
                    )
                },
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("2 passed" in s["content"] for s in statuses))

    def test_go_test_failure_creates_concern(self):
        """go test with FAIL → status + concern."""
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "go test ./..."},
                "tool_response": {
                    "stdout": "--- FAIL: TestFoo (0.00s)\nFAIL\tpkg\t0.3s"
                },
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_npm_test_detected(self):
        """npm test → recognized as jest framework."""
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "npm test"},
                "tool_response": {"stdout": "Tests:  3 passed, 3 total"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)


# ===========================================================================
# Simplify Gate — tracker re-trigger sequence
# ===========================================================================


class TestSimplifyGateIntegrationExtended(_IntegrationTestCase):
    def test_tracker_prevents_retrigger(self):
        """First stop blocks, second stop (same loop) passes through."""
        self._seed_events(
            [
                make_event("customer_input", content="build feature"),
                make_event("status", content="wrote", working_on=["src/app.ts"]),
            ]
        )
        # First stop — should block
        r1 = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r1.returncode, 2)
        self.assertIn("/simplify", r1.stderr)

        # Second stop — same events, tracker should prevent re-trigger
        r2 = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(r2.stdout.strip(), "")

    def test_new_loop_retriggers_after_tracker(self):
        """New customer_input resets tracker — blocks again."""
        ci1 = make_event("customer_input", content="task 1")
        self._seed_events(
            [ci1, make_event("status", content="wrote", working_on=["src/a.ts"])]
        )
        # First loop blocks
        r1 = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r1.returncode, 2)

        # New loop with new customer_input
        ci2 = make_event("customer_input", content="task 2")
        self._seed_events(
            [
                ci1,
                make_event("status", content="wrote", working_on=["src/a.ts"]),
                ci2,
                make_event("status", content="wrote2", working_on=["src/b.ts"]),
            ]
        )
        r2 = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r2.returncode, 2)
        self.assertIn("/simplify", r2.stderr)

    def test_stop_hook_active_passes_through(self):
        """stop_hook_active=True → exit 0 even with file changes."""
        self._seed_events(
            [
                make_event("customer_input", content="build"),
                make_event("status", content="wrote", working_on=["src/x.ts"]),
            ]
        )
        result = self._run_script(
            "simplify_gate.py",
            {
                "session_id": "int-test",
                "agent_id": "main",
                "stop_hook_active": True,
            },
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")


# ===========================================================================
# Advisory enforcement mode — conflict becomes warning instead of block
# ===========================================================================


class TestAdvisoryEnforcementIntegration(_IntegrationTestCase):
    def _make_advisory_plugin_root(self) -> Path:
        """Create a temp dir with advisory settings.json."""
        plugin_root = Path(tempfile.mkdtemp())
        (plugin_root / "settings.json").write_text(
            json.dumps({"enforcement": "advisory"})
        )
        return plugin_root

    def test_conflict_warns_instead_of_blocking(self):
        """Advisory mode: working_on conflict → exit 0 with warning, not exit 2."""
        self._seed_events(
            [
                make_event(
                    "status",
                    agent_id="other-agent",
                    working_on=[str(self.tmpdir / "src" / "app.ts")],
                ),
            ]
        )
        plugin_root = self._make_advisory_plugin_root()
        try:
            result = self._run_script_with_env(
                "pre_tool_use.py",
                {
                    "session_id": "int-test",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "src/app.ts"},
                    "agent_id": "main",
                    "cwd": str(self.tmpdir),
                },
                {"CLAUDE_PLUGIN_ROOT": str(plugin_root)},
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
            output = json.loads(result.stdout)
            ctx = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Advisory", ctx)
            self.assertIn("other-agent", ctx)
            self.assertIn("[enforcement: advisory]", ctx)
        finally:
            shutil.rmtree(plugin_root)

    def test_strict_mode_blocks(self):
        """Strict mode (default): working_on conflict → exit 2."""
        self._seed_events(
            [
                make_event(
                    "status",
                    agent_id="other-agent",
                    working_on=[str(self.tmpdir / "src" / "app.ts")],
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


# ===========================================================================
# Security review gate (Milestone 5.5)
# ===========================================================================


class TestSecurityReviewGateIntegration(_IntegrationTestCase):
    """Integration tests for security review push gate and detection paths."""

    def _get_head_hash(self) -> str:
        """Get HEAD hash from the temp git repo."""
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            cwd=self.tmpdir,
        ).strip()

    def _write_tracker(self, commit_hash: str) -> None:
        """Write a security tracker file in the SMM dir."""
        tracker = self.smm_dir / f".security-reviewed-{commit_hash}"
        tracker.write_text(
            json.dumps({"commit_hash": commit_hash, "ts": "2026-03-14T00:00:00"})
        )

    def test_git_push_blocked_no_review(self):
        """git push blocked without security review tracker."""
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push origin main"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("security", result.stderr.lower())
        self.assertIn("/security-review", result.stderr)

    def test_git_push_passes_with_tracker(self):
        """git push passes when tracker exists for current HEAD."""
        head = self._get_head_hash()
        self._write_tracker(head)
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push origin main"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

    def test_security_review_event_written(self):
        """Blocking a push writes security_review_requested event."""
        self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        events = self._read_events()
        sec_events = [e for e in events if e.get("type") == "security_review_requested"]
        self.assertEqual(len(sec_events), 1)

    def test_advisory_mode_warns(self):
        """Advisory mode: push warns instead of blocking."""
        plugin_root = Path(tempfile.mkdtemp())
        (plugin_root / "settings.json").write_text(
            json.dumps({"enforcement": "advisory"})
        )
        try:
            result = self._run_script_with_env(
                "pre_tool_use.py",
                {
                    "session_id": "int-test",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git push"},
                    "agent_id": "main",
                    "cwd": str(self.tmpdir),
                },
                {"CLAUDE_PLUGIN_ROOT": str(plugin_root)},
            )
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
            output = json.loads(result.stdout)
            ctx = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("security", ctx.lower())
        finally:
            shutil.rmtree(plugin_root)

    def test_user_prompt_writes_tracker(self):
        """/security-review in user prompt writes tracker file."""
        result = self._run_script(
            "user_prompt_log.py",
            {
                "session_id": "int-test",
                "prompt": "/security-review",
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        head = self._get_head_hash()
        tracker = self.smm_dir / f".security-reviewed-{head}"
        self.assertTrue(
            tracker.exists(),
            "Tracker should exist after /security-review",
        )

    def test_subagent_security_output_writes_tracker(self):
        """Security review output from subagent writes tracker file."""
        msg = (
            "## Security Review\n\nNo vulnerabilities found.\nSecurity audit complete."
        )
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "sub1",
                "last_assistant_message": msg,
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        head = self._get_head_hash()
        tracker = self.smm_dir / f".security-reviewed-{head}"
        self.assertTrue(
            tracker.exists(),
            "Tracker should exist after security output",
        )

    def test_new_commit_invalidates_tracker(self):
        """New commit creates new HEAD → old tracker invalid."""
        old_head = self._get_head_hash()
        self._write_tracker(old_head)

        # Create a new commit
        (self.tmpdir / "new_file").write_text("change")
        subprocess.run(["git", "add", "new_file"], cwd=self.tmpdir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "new commit"],
            cwd=self.tmpdir,
            capture_output=True,
        )

        # Push should now be blocked (new HEAD, old tracker)
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 2)

    def test_full_flow(self):
        """Full flow: push blocked → user sends /security-review → push passes."""
        # Step 1: push is blocked
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 2)

        # Step 2: user sends /security-review
        self._run_script(
            "user_prompt_log.py",
            {
                "session_id": "int-test",
                "prompt": "/security-review",
                "agent_id": "main",
            },
        )

        # Step 3: push now passes
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")


# ===========================================================================
# Milestone 6: CLAUDE.md & Skills
# ===========================================================================


class TestMilestone6Integration(_IntegrationTestCase):
    def test_session_start_behavioral_guide(self):
        """Subprocess: session_start.py stdout includes behavioral guide."""
        self._seed_events([make_event()])
        result = self._run_script(
            "session_start.py",
            {"session_id": "int-test", "source": "startup"},
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Honesty Principle", ctx)
        self.assertIn("Courage", ctx)
        self.assertIn("smm-protocol", ctx)
        self.assertIn("invoke these regularly", ctx.lower())

    def test_skill_files_parseable(self):
        """All 3 SKILL.md files exist and are non-trivial."""
        plugin_root = Path(__file__).parent.parent
        for name in ("smm-protocol", "xp-values", "pair-programming"):
            skill_file = plugin_root / "skills" / name / "SKILL.md"
            self.assertTrue(skill_file.is_file(), f"Missing: {skill_file}")
            content = skill_file.read_text()
            self.assertGreater(len(content), 500, f"{name} too short")
            self.assertTrue(content.startswith("---"), f"{name} missing frontmatter")

    def test_session_start_without_guide_file(self):
        """Subprocess: missing BEHAVIORAL_GUIDE.md degrades gracefully."""
        self._seed_events([make_event()])
        # Run with CLAUDE_PLUGIN_ROOT pointing to tmpdir (no guide file)
        result = self._run_script_with_env(
            "session_start.py",
            {"session_id": "int-test", "source": "startup"},
            {"CLAUDE_PLUGIN_ROOT": str(self.tmpdir)},
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        # Should still have GUPP and skills
        self.assertIn("Resume immediately", ctx)
        self.assertIn("smm-protocol", ctx)
        # Should NOT have guide content
        self.assertNotIn("Honesty Principle", ctx)


# ===========================================================================
# Milestone 6.5: Subagent nudge/block integration tests
# ===========================================================================


class TestMilestone65Integration(_IntegrationTestCase):
    def test_pre_tool_use_navigator_nudge(self):
        """Write tool → stdout contains xp-navigator nudge."""
        self._seed_events([make_event()])
        result = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-navigator", ctx)

    def test_post_tool_use_quality_nudge(self):
        """Write tool → stdout contains xp-quality-reviewer nudge."""
        self._seed_events([make_event()])
        result = self._run_script(
            "post_tool_use.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.ts", "content": "x"},
                "tool_response": {"success": True},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-quality-reviewer", ctx)

    def test_subagent_stop_plan_blocks(self):
        """Plan agent_type → exit 2 with plan reviewer instruction."""
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "plan-1",
                "agent_type": "Plan",
                "last_assistant_message": "1. Do stuff\n2. More stuff",
            },
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("xp-plan-reviewer", result.stderr)

    def test_subagent_stop_reviewer_nudge(self):
        """Regular subagent → stdout contains xp-subagent-reviewer nudge."""
        result = self._run_script(
            "subagent_stop.py",
            {
                "session_id": "int-test",
                "agent_id": "task-1",
                "last_assistant_message": "Done",
            },
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-subagent-reviewer", ctx)

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
        """All 6 agent .md files exist in agents/ directory."""
        agents_dir = Path(__file__).parent.parent / "agents"
        for name in (
            "xp-navigator",
            "xp-quality-reviewer",
            "xp-retrospective",
            "xp-customer-proxy",
            "xp-plan-reviewer",
            "xp-subagent-reviewer",
        ):
            path = agents_dir / f"{name}.md"
            self.assertTrue(path.is_file(), f"Missing: {path}")
            content = path.read_text()
            self.assertGreater(len(content), 500, f"{name} too short")
            self.assertTrue(content.startswith("---"), f"{name} missing frontmatter")


# ===========================================================================
# M7: Full Session Lifecycle
# ===========================================================================


class TestFullSessionLifecycle(_IntegrationTestCase):
    """M7: Chain session_start → pre_tool_use → post_tool_use → session_end."""

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
        # Should have behavioral guide + GUPP + skills
        self.assertIn("Resume immediately", ctx)
        self.assertIn("smm-protocol", ctx)
        # Customer proxy nudge for missing goals
        self.assertIn("xp-customer-proxy", ctx)

        # 2. Pre tool use (Write) — navigator nudge
        r2 = self._run_script(
            "pre_tool_use.py",
            {
                "session_id": "m7-lifecycle",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/feature.ts"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(r2.returncode, 0)
        output2 = json.loads(r2.stdout)
        ctx2 = output2["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-navigator", ctx2)

        # 3. Post tool use (Write) — status event + quality nudge
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
        output3 = json.loads(r3.stdout)
        ctx3 = output3["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-quality-reviewer", ctx3)

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


# ===========================================================================
# M7: Plan Review Full Flow
# ===========================================================================


class TestPlanReviewFlow(_IntegrationTestCase):
    """M7: Plan subagent → block, regular subagent → nudge."""

    def test_plan_subagent_blocks_with_reviewer(self):
        """Plan agent_type → exit 2 with xp-plan-reviewer instruction."""
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
        self.assertEqual(result.returncode, 2)
        self.assertIn("xp-plan-reviewer", result.stderr)

    def test_regular_subagent_nudges_reviewer(self):
        """Non-Plan subagent → exit 0 with xp-subagent-reviewer nudge."""
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
        ctx = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("xp-subagent-reviewer", ctx)

        # Should also have recorded a status event
        events = self._read_events()
        statuses = [e for e in events if e["type"] == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertIn("task-2", statuses[0]["content"])


# ===========================================================================
# M7: 3-Session Accumulation
# ===========================================================================


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

        # Mark retro as done via retrospective event
        events = self._read_events()
        retro_event = make_event(
            "retrospective",
            content="Retrospective complete",
        )
        events.append(retro_event)
        self._seed_events(events)

        # Add more events for session 2 work
        events = self._read_events()
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


# ===========================================================================
# M7: Compaction → Re-injection
# ===========================================================================


class TestCompactionReinjection(_IntegrationTestCase):
    """M7: After compaction, session_start re-injects full SMM."""

    def test_compact_reinjects_smm(self):
        """Seed → materialize → backup → truncate → session_start."""
        # 1. Seed events and materialize
        self._seed_events(
            [
                make_event(
                    "decision",
                    content="Use PostgreSQL",
                    topic="database",
                ),
                make_event("status", content="Working on DB"),
            ]
        )

        # 2. Run pre_compact to create backup
        self._run_script(
            "pre_compact.py",
            {"session_id": "compact-test"},
        )
        backups_dir = self.smm_dir / "backups"
        self.assertTrue(backups_dir.exists())

        # 3. Truncate events.jsonl (simulate compaction)
        (self.smm_dir / "events.jsonl").write_text("")

        # 4. Session start with compact source re-injects
        r = self._run_script(
            "session_start.py",
            {"session_id": "compact-test", "source": "compact"},
        )
        self.assertEqual(r.returncode, 0)
        output = json.loads(r.stdout)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        # Should have SMM context (materialized from empty log)
        self.assertIn("Resume immediately", ctx)
        self.assertIn("smm-protocol", ctx)


if __name__ == "__main__":
    unittest.main()
