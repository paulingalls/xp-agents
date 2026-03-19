#!/usr/bin/env python3
"""Integration tests: extended and security tests.

Tests for simplify gate, bash failure, lint check extended, bash post tool
extended, and security review gate.
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


class TestSimplifyGateIntegration(_IntegrationTestCase):
    def test_file_changes_blocks_stop(self):
        """customer_input + status with working_on → decision block with /simplify."""
        self._seed_events(
            [
                make_event("customer_input", content="build feature"),
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        result = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["decision"], "block")
        self.assertIn("/simplify", data["reason"])

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
                "agent_type": "xp-navigator",
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


class TestSimplifyGateIntegrationExtended(_IntegrationTestCase):
    def test_tracker_prevents_retrigger(self):
        """First stop blocks, second stop (same loop) passes through."""
        self._seed_events(
            [
                make_event("customer_input", content="build feature"),
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/app.ts", "src/util.ts", "src/index.ts"],
                ),
            ]
        )
        # First stop — should block via decision JSON
        r1 = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r1.returncode, 0)
        d1 = json.loads(r1.stdout)
        self.assertEqual(d1["decision"], "block")
        self.assertIn("/simplify", d1["reason"])

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
            [
                ci1,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/a.ts", "src/b.ts", "src/c.ts"],
                ),
            ]
        )
        # First loop blocks
        r1 = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(json.loads(r1.stdout)["decision"], "block")

        # New loop with new customer_input
        ci2 = make_event("customer_input", content="task 2")
        self._seed_events(
            [
                ci1,
                make_event(
                    "status",
                    content="wrote",
                    working_on=["src/a.ts", "src/b.ts", "src/c.ts"],
                ),
                ci2,
                make_event(
                    "status",
                    content="wrote2",
                    working_on=["src/d.ts", "src/e.ts", "src/f.ts"],
                ),
            ]
        )
        r2 = self._run_script(
            "simplify_gate.py",
            {"session_id": "int-test", "agent_id": "main"},
        )
        self.assertEqual(r2.returncode, 0)
        d2 = json.loads(r2.stdout)
        self.assertEqual(d2["decision"], "block")
        self.assertIn("/simplify", d2["reason"])

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
            "pre_tool_bash.py",
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

    def test_security_review_event_written(self):
        """Blocking a push writes security_review_requested event."""
        self._run_script(
            "pre_tool_bash.py",
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
            "pre_tool_bash.py",
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
            "pre_tool_bash.py",
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
            "pre_tool_bash.py",
            {
                "session_id": "int-test",
                "tool_name": "Bash",
                "tool_input": {"command": "git push"},
                "agent_id": "main",
                "cwd": str(self.tmpdir),
            },
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")


if __name__ == "__main__":
    unittest.main()
