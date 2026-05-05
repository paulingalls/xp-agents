#!/usr/bin/env python3
"""Integration tests: bash failure, lint check, bash post-tool."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase
from event_schema import EVENT_TYPE_CONCERN, EVENT_TYPE_STATUS


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
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
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
            if e.get("type") == EVENT_TYPE_CONCERN
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
                "agent_type": "xp-housekeeper",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)

    def test_no_linter_nudge_only_once(self):
        """Second run without linter config → no duplicate nudge."""
        r1 = self._run_script(
            "lint_check.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.py", "content": "x"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertIn("linter", r1.stdout.lower())
        r2 = self._run_script(
            "lint_check.py",
            {
                "session_id": "int-test",
                "tool_name": "Write",
                "tool_input": {"file_path": "src/app.py", "content": "x"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(r2.stdout, "", "Should nudge exactly once per session")


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
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
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
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
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
        concerns = [e for e in events if e.get("type") == EVENT_TYPE_CONCERN]
        self.assertTrue(len(concerns) >= 1)

    def test_unittest_results_create_events(self):
        """python3 -m unittest output → status event."""
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest tests/test_foo.py -v"},
                "tool_response": {"stdout": "Ran 50 tests in 1.2s\n\nOK"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("50 passed" in s["content"] for s in statuses))

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
        statuses = [e for e in events if e.get("type") == EVENT_TYPE_STATUS]
        self.assertTrue(len(statuses) >= 1)


if __name__ == "__main__":
    unittest.main()
