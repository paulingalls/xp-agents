#!/usr/bin/env python3
"""Tests for bash_post_tool.py and bash_failure.py hooks.

Split from the original test_post_tool.py.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import _common
import bash_failure
import bash_post_tool
import security
from conftest import _HookTestCase, _make_bash_input

# ===========================================================================
# bash_post_tool.py tests — Milestone 3.3
# ===========================================================================


class TestIsGitCommit(unittest.TestCase):
    def test_git_commit_m(self):
        self.assertTrue(security.is_git_commit("git commit -m 'msg'"))

    def test_git_commit_am(self):
        self.assertTrue(security.is_git_commit("git commit -am 'msg'"))

    def test_git_commit_with_path(self):
        self.assertTrue(security.is_git_commit("cd /tmp && git commit -m 'x'"))

    def test_not_git_status(self):
        self.assertFalse(security.is_git_commit("git status"))

    def test_not_ls(self):
        self.assertFalse(security.is_git_commit("ls -la"))

    def test_git_commit_no_message(self):
        self.assertTrue(security.is_git_commit("git commit"))


class TestIsTestRun(unittest.TestCase):
    def test_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("pytest"), "pytest")

    def test_python_m_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("python -m pytest"), "pytest")

    def test_python3_m_pytest(self):
        self.assertEqual(bash_post_tool.is_test_run("python3 -m pytest"), "pytest")

    def test_jest(self):
        self.assertEqual(bash_post_tool.is_test_run("npx jest"), "jest")

    def test_jest_bare(self):
        self.assertEqual(bash_post_tool.is_test_run("jest"), "jest")

    def test_go_test(self):
        self.assertEqual(bash_post_tool.is_test_run("go test ./..."), "go")

    def test_not_test(self):
        self.assertIsNone(bash_post_tool.is_test_run("ls -la"))

    def test_npm_test(self):
        self.assertEqual(bash_post_tool.is_test_run("npm test"), "jest")


class TestParseCommitMessage(unittest.TestCase):
    def test_standard_output(self):
        response = "[main abc123] Add auth module\n 3 files changed, 45 insertions(+)"
        result = bash_post_tool.parse_commit_message(response)
        self.assertEqual(result, "Add auth module")

    def test_no_match(self):
        result = bash_post_tool.parse_commit_message("error: something went wrong")
        self.assertIsNone(result)


class TestParseTestResults(unittest.TestCase):
    def test_pytest_pass(self):
        output = "===== 5 passed in 0.3s ====="
        result = bash_post_tool.parse_test_results(output, "pytest")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_pytest_fail(self):
        output = "===== 3 passed, 2 failed in 1.2s ====="
        result = bash_post_tool.parse_test_results(output, "pytest")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_jest_pass(self):
        output = "Tests:  5 passed, 5 total"
        result = bash_post_tool.parse_test_results(output, "jest")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_jest_fail(self):
        output = "Tests:  2 failed, 3 passed, 5 total"
        result = bash_post_tool.parse_test_results(output, "jest")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_go_pass(self):
        output = "ok  \tgithub.com/user/pkg\t0.3s"
        result = bash_post_tool.parse_test_results(output, "go")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)

    def test_go_fail(self):
        output = "--- FAIL: TestSomething (0.00s)\nFAIL\tgithub.com/user/pkg\t0.3s"
        result = bash_post_tool.parse_test_results(output, "go")
        self.assertEqual(result["failed"], 1)

    def test_unittest_pass(self):
        output = "Ran 821 tests in 32.346s\n\nOK"
        result = bash_post_tool.parse_test_results(output, "unittest")
        self.assertEqual(result["passed"], 821)
        self.assertEqual(result["failed"], 0)

    def test_unittest_fail(self):
        output = "Ran 50 tests in 1.2s\n\nFAILED (failures=2, errors=1)"
        result = bash_post_tool.parse_test_results(output, "unittest")
        self.assertEqual(result["passed"], 47)
        self.assertEqual(result["failed"], 3)
        self.assertEqual(result["errors"], 1)

    def test_is_test_run_unittest(self):
        self.assertEqual(
            bash_post_tool.is_test_run("python3 -m unittest tests/test_foo.py -v"),
            "unittest",
        )
        self.assertIsNone(bash_post_tool.is_test_run("echo unittest"))

    def test_xcodebuild_pass(self):
        output = (
            "Executed 12 tests, with 0 failures (0 unexpected) in 1.234 (2.345) seconds"
        )
        result = bash_post_tool.parse_test_results(output, "xcodebuild")
        self.assertEqual(result["passed"], 12)
        self.assertEqual(result["failed"], 0)

    def test_xcodebuild_fail(self):
        output = (
            "Executed 12 tests, with 3 failures (2 unexpected) in 1.234 (2.345) seconds"
        )
        result = bash_post_tool.parse_test_results(output, "xcodebuild")
        self.assertEqual(result["passed"], 9)
        self.assertEqual(result["failed"], 3)

    def test_swift_test_pass(self):
        output = (
            "Executed 5 tests, with 0 failures (0 unexpected) in 0.456 (0.789) seconds"
        )
        result = bash_post_tool.parse_test_results(output, "swift")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_is_test_run_xcodebuild(self):
        self.assertEqual(
            bash_post_tool.is_test_run("xcodebuild test -scheme MyApp"),
            "xcodebuild",
        )
        self.assertEqual(
            bash_post_tool.is_test_run("xcodebuild -workspace Foo.xcworkspace test"),
            "xcodebuild",
        )
        self.assertIsNone(bash_post_tool.is_test_run("xcodebuild build"))

    def test_is_test_run_swift(self):
        self.assertEqual(
            bash_post_tool.is_test_run("swift test"),
            "swift",
        )
        self.assertEqual(
            bash_post_tool.is_test_run("swift test --filter MyTests"),
            "swift",
        )

    # --- Rust ---
    def test_cargo_test_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("cargo test"), "cargo")

    def test_cargo_pass(self):
        output = "test result: ok. 15 passed; 0 failed; 0 ignored"
        result = bash_post_tool.parse_test_results(output, "cargo")
        self.assertEqual(result["passed"], 15)
        self.assertEqual(result["failed"], 0)

    def test_cargo_fail(self):
        output = "test result: FAILED. 10 passed; 3 failed; 0 ignored"
        result = bash_post_tool.parse_test_results(output, "cargo")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 3)

    # --- Maven/Gradle ---
    def test_mvn_test_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("mvn test"), "maven")

    def test_gradle_test_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("./gradlew test"), "gradle")

    def test_maven_pass(self):
        output = "Tests run: 10, Failures: 0, Errors: 0, Skipped: 1"
        result = bash_post_tool.parse_test_results(output, "maven")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    def test_maven_fail(self):
        output = "Tests run: 10, Failures: 2, Errors: 1, Skipped: 0"
        result = bash_post_tool.parse_test_results(output, "maven")
        self.assertEqual(result["passed"], 7)
        self.assertEqual(result["failed"], 3)

    # --- Ruby ---
    def test_rspec_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("rspec"), "rspec")

    def test_rspec_pass(self):
        output = "10 examples, 0 failures"
        result = bash_post_tool.parse_test_results(output, "rspec")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    def test_minitest_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("rake test"), "minitest")

    def test_minitest_fail(self):
        output = "5 runs, 10 assertions, 1 failures, 1 errors"
        result = bash_post_tool.parse_test_results(output, "minitest")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    # --- PHP ---
    def test_phpunit_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("phpunit"), "phpunit")

    def test_phpunit_pass(self):
        output = "OK (10 tests, 20 assertions)"
        result = bash_post_tool.parse_test_results(output, "phpunit")
        self.assertEqual(result["passed"], 10)

    def test_phpunit_fail(self):
        output = "FAILURES!\nTests: 10, Assertions: 20, Failures: 3."
        result = bash_post_tool.parse_test_results(output, "phpunit")
        self.assertEqual(result["passed"], 7)
        self.assertEqual(result["failed"], 3)

    # --- .NET ---
    def test_dotnet_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("dotnet test"), "dotnet")

    def test_dotnet_pass(self):
        output = "Passed!  - Failed: 0, Passed: 5, Skipped: 0, Total: 5"
        result = bash_post_tool.parse_test_results(output, "dotnet")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    # --- Dart ---
    def test_dart_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("dart test"), "dart")
        self.assertEqual(bash_post_tool.is_test_run("flutter test"), "dart")

    def test_dart_pass(self):
        output = "+5: All tests passed!"
        result = bash_post_tool.parse_test_results(output, "dart")
        self.assertEqual(result["passed"], 5)

    def test_dart_fail(self):
        output = "+3 -2: Some tests failed."
        result = bash_post_tool.parse_test_results(output, "dart")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    # --- Elixir ---
    def test_elixir_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("mix test"), "elixir")

    def test_elixir_pass(self):
        output = "10 tests, 0 failures"
        result = bash_post_tool.parse_test_results(output, "elixir")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    # --- CTest ---
    def test_ctest_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("ctest"), "ctest")

    def test_ctest_pass(self):
        output = "100% tests passed, 0 tests failed out of 10"
        result = bash_post_tool.parse_test_results(output, "ctest")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    # --- Vitest ---
    def test_vitest_detected(self):
        self.assertEqual(bash_post_tool.is_test_run("npx vitest"), "vitest")


class TestBashPostTool(_HookTestCase):
    def test_git_commit_auto_drafts_decision(self):
        with patch("bash_post_tool.count_commit_files", return_value=3):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Add auth'",
                    stdout="[main abc123] Add auth\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        decisions = [e for e in events if e.get("type") == "decision"]
        self.assertEqual(len(decisions), 1)
        self.assertTrue(decisions[0].get("metadata", {}).get("draft"))
        self.assertIn("Add auth", decisions[0]["content"])

    def test_git_commit_small_no_concern(self):
        with patch("bash_post_tool.count_commit_files", return_value=3):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Fix bug'",
                    stdout="[main abc123] Fix bug\n 3 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 0)

    def test_git_commit_large_appends_concern(self):
        with patch("bash_post_tool.count_commit_files", return_value=12):
            bash_post_tool.run(
                _make_bash_input(
                    command="git commit -m 'Big change'",
                    stdout="[main abc123] Big change\n 12 files changed",
                ),
                smm_dir=self.smm_dir,
            )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("12 files" in c["content"] for c in concerns))

    def test_commit_threshold_from_settings(self):
        settings_path = Path(__file__).parent.parent.parent / "settings.json"
        original = settings_path.read_text()
        try:
            settings_path.write_text(json.dumps({"commit_size_threshold": 5}))
            with patch("bash_post_tool.count_commit_files", return_value=6):
                bash_post_tool.run(
                    _make_bash_input(
                        command="git commit -m 'x'",
                        stdout="[main a] x\n 6 files changed",
                    ),
                    smm_dir=self.smm_dir,
                )
            events = _common.read_events_raw(self.smm_dir)
            concerns = [e for e in events if e.get("type") == "concern"]
            self.assertTrue(len(concerns) >= 1)
        finally:
            settings_path.write_text(original)

    def test_commit_threshold_default(self):
        self.assertEqual(bash_post_tool.load_commit_threshold(), 10)

    def test_pytest_pass(self):
        bash_post_tool.run(
            _make_bash_input(
                command="python3 -m pytest tests/",
                stdout="===== 5 passed in 0.3s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)
        self.assertTrue(any("5 passed" in s["content"] for s in statuses))

    def test_pytest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="pytest",
                stdout="===== 3 passed, 2 failed in 1.2s =====",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)
        self.assertTrue(any("fail" in c["content"].lower() for c in concerns))

    def test_jest_pass(self):
        bash_post_tool.run(
            _make_bash_input(command="npx jest", stdout="Tests:  5 passed, 5 total"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_jest_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="npx jest",
                stdout="Tests:  2 failed, 3 passed, 5 total",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_go_test_pass(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="ok  \tgithub.com/user/pkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertTrue(len(statuses) >= 1)

    def test_go_test_fail(self):
        bash_post_tool.run(
            _make_bash_input(
                command="go test ./...",
                stdout="--- FAIL: TestSomething (0.00s)\nFAIL\tpkg\t0.3s",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertTrue(len(concerns) >= 1)

    def test_non_git_non_test_ignored(self):
        bash_post_tool.run(
            _make_bash_input(command="ls -la", stdout="total 0"),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_xp_agent_skips(self):
        bash_post_tool.run(
            _make_bash_input(
                command="git commit -m 'x'",
                stdout="[main a] x",
                agent_type="xp-housekeeping",
            ),
            smm_dir=self.smm_dir,
        )
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_graceful_no_smm_dir(self):
        fake_dir = Path(tempfile.mkdtemp()) / "nonexistent"
        bash_post_tool.run(
            _make_bash_input(command="git commit -m 'x'", stdout="[main a] x"),
            smm_dir=fake_dir,
        )

    def test_git_commit_parse_message(self):
        response = "[main abc123] Fix login bug\n 1 file changed"
        self.assertEqual(bash_post_tool.parse_commit_message(response), "Fix login bug")


# ===========================================================================
# Bash Failure (PostToolUseFailure)
# ===========================================================================


def _make_bash_failure_input(
    command: str = "echo hi", error: str = "exit code 1", **overrides
) -> dict:
    """Build a canonical PostToolUseFailure Bash input dict."""
    data = {
        "session_id": "t",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": error,
        "is_interrupt": False,
        "agent_id": "main",
    }
    data.update(overrides)
    return data


class TestBashFailure(_HookTestCase):
    """Tests for bash_failure.py PostToolUseFailure handler."""

    def setUp(self):
        super().setUp()
        self.mod = bash_failure

    def test_xp_agent_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_type="xp-nav"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_interrupt_skips(self):
        inp = _make_bash_failure_input(
            command="pytest", error="interrupted", is_interrupt=True
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_no_smm_dir_degrades(self):
        inp = _make_bash_failure_input(command="pytest", error="exit 1")
        self.mod.run(inp, smm_dir=Path("/nonexistent/smm"))
        # No crash

    def test_non_test_command_ignored(self):
        inp = _make_bash_failure_input(command="ls -la", error="exit 2")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)

    def test_pytest_failure_records_status_and_concern(self):
        inp = _make_bash_failure_input(
            command="python3 -m pytest tests/",
            error="Command exited with non-zero status code 1",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(statuses), 1)
        self.assertIn("pytest", statuses[0]["content"])
        self.assertIn("failed", statuses[0]["content"].lower())
        self.assertEqual(len(concerns), 1)
        self.assertEqual(concerns[0]["severity"], "high")

    def test_jest_failure_records_concern(self):
        inp = _make_bash_failure_input(command="npx jest", error="exit code 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("jest", concerns[0]["content"].lower())

    def test_go_test_failure_records_concern(self):
        inp = _make_bash_failure_input(command="go test ./...", error="exit 1")
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        concerns = [e for e in events if e.get("type") == "concern"]
        self.assertEqual(len(concerns), 1)
        self.assertIn("go", concerns[0]["content"].lower())

    def test_error_message_included_in_status(self):
        inp = _make_bash_failure_input(
            command="pytest",
            error="Command exited with non-zero status code 2",
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        statuses = [e for e in events if e.get("type") == "status"]
        self.assertIn("non-zero status code 2", statuses[0]["content"])


class TestBashFailureSecurity(_HookTestCase):
    """Security tests for bash_failure.py."""

    def setUp(self):
        super().setUp()
        self.mod = bash_failure

    def test_path_traversal_agent_id_rejected(self):
        inp = _make_bash_failure_input(
            command="pytest", error="exit 1", agent_id="../../evil"
        )
        self.mod.run(inp, smm_dir=self.smm_dir)
        events = _common.read_events_raw(self.smm_dir)
        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()
