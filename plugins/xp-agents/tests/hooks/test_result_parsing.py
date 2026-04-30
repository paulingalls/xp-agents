#!/usr/bin/env python3
"""Tests for parse_test_results across every supported framework.

Pure parsing tests — no SMM state needed. Split from test_bash_parsing.py
(story-008) when that file crossed the 500-line cap.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import test_parsing


class TestParseTestResults(unittest.TestCase):
    def test_pytest_pass(self):
        output = "===== 5 passed in 0.3s ====="
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_pytest_fail(self):
        output = "===== 3 passed, 2 failed in 1.2s ====="
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_jest_pass(self):
        output = "Tests:  5 passed, 5 total"
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_jest_fail(self):
        output = "Tests:  2 failed, 3 passed, 5 total"
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    def test_go_pass(self):
        output = "ok  \tgithub.com/user/pkg\t0.3s"
        result = test_parsing.parse_test_results(output, "go")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["failed"], 0)

    def test_go_fail(self):
        output = "--- FAIL: TestSomething (0.00s)\nFAIL\tgithub.com/user/pkg\t0.3s"
        result = test_parsing.parse_test_results(output, "go")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["failed"], 1)

    def test_unittest_pass(self):
        output = "Ran 821 tests in 32.346s\n\nOK"
        result = test_parsing.parse_test_results(output, "unittest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 821)
        self.assertEqual(result["failed"], 0)

    def test_unittest_fail(self):
        output = "Ran 50 tests in 1.2s\n\nFAILED (failures=2, errors=1)"
        result = test_parsing.parse_test_results(output, "unittest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 47)
        self.assertEqual(result["failed"], 3)
        self.assertEqual(result["errors"], 1)

    def test_is_test_run_unittest(self):
        self.assertEqual(
            test_parsing.is_test_run("python3 -m unittest tests/test_foo.py -v"),
            "unittest",
        )
        self.assertIsNone(test_parsing.is_test_run("echo unittest"))

    def test_xcodebuild_pass(self):
        output = (
            "Executed 12 tests, with 0 failures (0 unexpected) in 1.234 (2.345) seconds"
        )
        result = test_parsing.parse_test_results(output, "xcodebuild")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 12)
        self.assertEqual(result["failed"], 0)

    def test_xcodebuild_fail(self):
        output = (
            "Executed 12 tests, with 3 failures (2 unexpected) in 1.234 (2.345) seconds"
        )
        result = test_parsing.parse_test_results(output, "xcodebuild")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 9)
        self.assertEqual(result["failed"], 3)

    def test_swift_test_pass(self):
        output = (
            "Executed 5 tests, with 0 failures (0 unexpected) in 0.456 (0.789) seconds"
        )
        result = test_parsing.parse_test_results(output, "swift")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_is_test_run_xcodebuild(self):
        self.assertEqual(
            test_parsing.is_test_run("xcodebuild test -scheme MyApp"),
            "xcodebuild",
        )
        self.assertEqual(
            test_parsing.is_test_run("xcodebuild -workspace Foo.xcworkspace test"),
            "xcodebuild",
        )
        self.assertIsNone(test_parsing.is_test_run("xcodebuild build"))

    def test_is_test_run_swift(self):
        self.assertEqual(
            test_parsing.is_test_run("swift test"),
            "swift",
        )
        self.assertEqual(
            test_parsing.is_test_run("swift test --filter MyTests"),
            "swift",
        )

    # --- Rust ---
    def test_cargo_test_detected(self):
        self.assertEqual(test_parsing.is_test_run("cargo test"), "cargo")

    def test_cargo_pass(self):
        output = "test result: ok. 15 passed; 0 failed; 0 ignored"
        result = test_parsing.parse_test_results(output, "cargo")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 15)
        self.assertEqual(result["failed"], 0)

    def test_cargo_fail(self):
        output = "test result: FAILED. 10 passed; 3 failed; 0 ignored"
        result = test_parsing.parse_test_results(output, "cargo")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 3)

    # --- Maven/Gradle ---
    def test_mvn_test_detected(self):
        self.assertEqual(test_parsing.is_test_run("mvn test"), "maven")

    def test_gradle_test_detected(self):
        self.assertEqual(test_parsing.is_test_run("./gradlew test"), "gradle")

    def test_maven_pass(self):
        output = "Tests run: 10, Failures: 0, Errors: 0, Skipped: 1"
        result = test_parsing.parse_test_results(output, "maven")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    def test_maven_fail(self):
        output = "Tests run: 10, Failures: 2, Errors: 1, Skipped: 0"
        result = test_parsing.parse_test_results(output, "maven")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 7)
        self.assertEqual(result["failed"], 3)

    # --- Ruby ---
    def test_rspec_detected(self):
        self.assertEqual(test_parsing.is_test_run("rspec"), "rspec")

    def test_rspec_pass(self):
        output = "10 examples, 0 failures"
        result = test_parsing.parse_test_results(output, "rspec")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    def test_minitest_detected(self):
        self.assertEqual(test_parsing.is_test_run("rake test"), "minitest")

    def test_minitest_fail(self):
        output = "5 runs, 10 assertions, 1 failures, 1 errors"
        result = test_parsing.parse_test_results(output, "minitest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    # --- PHP ---
    def test_phpunit_detected(self):
        self.assertEqual(test_parsing.is_test_run("phpunit"), "phpunit")

    def test_phpunit_pass(self):
        output = "OK (10 tests, 20 assertions)"
        result = test_parsing.parse_test_results(output, "phpunit")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 10)

    def test_phpunit_fail(self):
        output = "FAILURES!\nTests: 10, Assertions: 20, Failures: 3."
        result = test_parsing.parse_test_results(output, "phpunit")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 7)
        self.assertEqual(result["failed"], 3)

    # --- .NET ---
    def test_dotnet_detected(self):
        self.assertEqual(test_parsing.is_test_run("dotnet test"), "dotnet")

    def test_dotnet_pass(self):
        output = "Passed!  - Failed: 0, Passed: 5, Skipped: 0, Total: 5"
        result = test_parsing.parse_test_results(output, "dotnet")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    # --- Dart ---
    def test_dart_detected(self):
        self.assertEqual(test_parsing.is_test_run("dart test"), "dart")
        self.assertEqual(test_parsing.is_test_run("flutter test"), "dart")

    def test_dart_pass(self):
        output = "+5: All tests passed!"
        result = test_parsing.parse_test_results(output, "dart")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 5)

    def test_dart_fail(self):
        output = "+3 -2: Some tests failed."
        result = test_parsing.parse_test_results(output, "dart")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    # --- Elixir ---
    def test_elixir_detected(self):
        self.assertEqual(test_parsing.is_test_run("mix test"), "elixir")

    def test_elixir_pass(self):
        output = "10 tests, 0 failures"
        result = test_parsing.parse_test_results(output, "elixir")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    # --- CTest ---
    def test_ctest_detected(self):
        self.assertEqual(test_parsing.is_test_run("ctest"), "ctest")

    def test_ctest_pass(self):
        output = "100% tests passed, 0 tests failed out of 10"
        result = test_parsing.parse_test_results(output, "ctest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 0)

    # --- Vitest ---
    def test_vitest_detected(self):
        self.assertEqual(test_parsing.is_test_run("npx vitest"), "vitest")

    # --- Bun ---
    def test_bun_test_detected(self):
        self.assertEqual(test_parsing.is_test_run("bun test"), "bun")

    def test_bun_pass(self):
        output = "130 pass\n 0 fail\n 418 expect() calls"
        result = test_parsing.parse_test_results(output, "bun")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 130)
        self.assertEqual(result["failed"], 0)

    def test_bun_fail(self):
        output = "8 pass\n 2 fail\n 30 expect() calls"
        result = test_parsing.parse_test_results(output, "bun")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 8)
        self.assertEqual(result["failed"], 2)

    # --- Playwright ---
    def test_playwright_pass(self):
        output = "Running 5 tests using 2 workers\n\n  5 passed (12.3s)"
        result = test_parsing.parse_test_results(output, "playwright")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 5)
        self.assertEqual(result["failed"], 0)

    def test_playwright_fail(self):
        output = "Running 5 tests using 2 workers\n\n  2 failed\n  3 passed (12.3s)"
        result = test_parsing.parse_test_results(output, "playwright")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 3)
        self.assertEqual(result["failed"], 2)

    # --- Tristate status field (zero/parser_failed cases; PARSED is covered
    # by the per-framework pass/fail tests above which already assert status). ---
    def test_pytest_zero_no_tests_ran_returns_zero(self):
        output = "===== no tests ran in 0.1s ====="
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)

    def test_pytest_zero_collected_zero_items_returns_zero(self):
        output = "collected 0 items\n\n===== no tests ran in 0.1s ====="
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["status"], "zero")

    def test_pytest_garbled_returns_parser_failed(self):
        output = "garbled output with no counts"
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["status"], "parser_failed")

    def test_pytest_errors_only_folds_into_failed(self):
        # Collection-only errors (no passed/failed line). Errors fold into
        # failed so test_passed=False and test_count=N at the consumer.
        output = "===== 2 errors in 0.5s ====="
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["errors"], 2)

    def test_cargo_zero_counts_returns_zero(self):
        # Long-tail framework: matched-but-zero → ZERO via bistate fallback.
        output = "test result: ok. 0 passed; 0 failed; 0 ignored"
        result = test_parsing.parse_test_results(output, "cargo")
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)

    def test_unittest_zero_returns_zero(self):
        output = "Ran 0 tests in 0.0s\n\nOK"
        result = test_parsing.parse_test_results(output, "unittest")
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["failed"], 0)

    def test_unittest_garbled_returns_parser_failed(self):
        output = "garbled"
        result = test_parsing.parse_test_results(output, "unittest")
        self.assertEqual(result["status"], "parser_failed")

    def test_jest_zero_returns_zero(self):
        output = "Tests:       0 passed, 0 total"
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["status"], "zero")
        self.assertEqual(result["passed"], 0)

    def test_jest_no_tests_found_returns_zero(self):
        output = "No tests found, exiting with code 1"
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["status"], "zero")

    def test_jest_garbled_returns_parser_failed(self):
        output = "garbled"
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["status"], "parser_failed")


if __name__ == "__main__":
    unittest.main()
