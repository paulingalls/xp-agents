#!/usr/bin/env python3
"""Integration tests: extended and commit gate tests.

Tests for bash failure, lint check extended, bash post tool extended,
and commit security triage gate.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from conftest import _IntegrationTestCase


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
                "agent_type": "xp-housekeeping",
            },
        )
        self.assertEqual(result.returncode, 0)
        events = self._read_events()
        self.assertEqual(len(events), 0)

    def test_no_linter_question_only_once(self):
        """Second run without linter config → no duplicate question."""
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
        questions = [e for e in events if e.get("type") == "question"]
        self.assertEqual(len(questions), 1, "Should ask exactly once")


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
        statuses = [e for e in events if e.get("type") == "status"]
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
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)


class TestCommitGateIntegration(_IntegrationTestCase):
    """Integration tests for commit security triage gate."""

    def _stage_code_file(self) -> None:
        """Stage a code file so the commit gate sees production code."""
        code_file = self.tmpdir / "src" / "app.ts"
        code_file.parent.mkdir(parents=True, exist_ok=True)
        code_file.write_text("export const x = 1;\n")
        subprocess.run(
            ["git", "add", "src/app.ts"],
            cwd=self.tmpdir,
            capture_output=True,
        )

    def _write_triage_marker(self) -> None:
        """Write a .security-triaged marker in the SMM dir."""
        marker = self.smm_dir / ".security-triaged"
        marker.write_text(json.dumps({"ts": "2026-03-19T00:00:00"}))

    def test_git_commit_blocked_no_triage(self):
        """git commit blocked without security triage marker."""
        self._stage_code_file()
        result = self._run_script(
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("/xp-security-triage", result.stderr)

    def test_git_commit_passes_with_marker(self):
        """git commit passes when triage marker exists."""
        self._write_triage_marker()
        result = self._run_script(
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

    def test_git_push_not_gated(self):
        """git push is not gated anymore."""
        result = self._run_script(
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push origin main"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

    def test_marker_consumed_after_commit(self):
        """Triage marker is consumed after a successful git commit."""
        self._write_triage_marker()
        marker = self.smm_dir / ".security-triaged"
        self.assertTrue(marker.exists())

        # Simulate successful commit via bash_post_tool
        result = self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "tool_response": {"stdout": "[main abc1234] test"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertFalse(marker.exists(), "Marker should be consumed after commit")

    def test_security_review_skill_writes_marker(self):
        """PostToolUse:Skill for /security-review writes triage marker."""
        result = self._run_script(
            "review_cycle_done.py",
            {
                "session_id": "int-test",
                "tool_name": "Skill",
                "tool_input": {"skill": "security-review"},
                "agent_id": "main",
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        marker = self.smm_dir / ".security-triaged"
        self.assertTrue(marker.exists(), "Marker should exist after /security-review")

    def test_full_flow(self):
        """Full flow: commit blocked → triage → commit passes → marker consumed."""
        self._stage_code_file()
        # Step 1: commit is blocked
        result = self._run_script(
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 2)

        # Step 2: security review skill writes marker
        self._run_script(
            "review_cycle_done.py",
            {
                "session_id": "int-test",
                "tool_name": "Skill",
                "tool_input": {"skill": "security-review"},
                "agent_id": "main",
            },
        )

        # Step 3: commit now passes
        result = self._run_script(
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")

        # Step 4: marker is consumed after commit
        self._run_script(
            "bash_post_tool.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m 'test'"},
                "tool_response": {"stdout": "[main abc1234] test"},
                "cwd": str(self.tmpdir),
                "agent_id": "main",
            },
        )
        marker = self.smm_dir / ".security-triaged"
        self.assertFalse(marker.exists(), "Marker should be consumed after commit")


if __name__ == "__main__":
    unittest.main()
