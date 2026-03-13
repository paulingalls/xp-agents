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

    def test_retro_triggered_with_enough_events(self):
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
        self.assertIn("retrospective", ctx.lower())


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
        self.assertIn("SMM Delta", ctx)
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


if __name__ == "__main__":
    unittest.main()
