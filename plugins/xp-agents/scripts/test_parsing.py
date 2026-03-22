#!/usr/bin/env python3
"""Test framework detection and result parsing.

Pure functions for identifying test commands and parsing their output.
No SMM dependencies — stdlib only (re, json).

Extracted from bash_post_tool.py for module size management.
"""

import re

# ---------------------------------------------------------------------------
# Command classification
# ---------------------------------------------------------------------------


def is_test_run(command: str) -> str | None:
    """Check if the command is a test run. Returns framework name or None."""
    # Python
    if re.search(r"\bpytest\b", command) or re.search(
        r"python3?\s+-m\s+pytest\b", command
    ):
        return "pytest"
    if re.search(r"python3?\s+-m\s+unittest\b", command):
        return "unittest"
    # JavaScript/TypeScript
    if re.search(r"\b(npx\s+)?jest\b", command) or re.search(
        r"\bnpm\s+test\b", command
    ):
        return "jest"
    if re.search(r"\b(npx\s+)?vitest\b", command):
        return "vitest"
    if re.search(r"\bbun\s+test\b", command):
        return "bun"
    # Go
    if re.search(r"\bgo\s+test\b", command):
        return "go"
    # Swift/Xcode
    if re.search(r"\bxcodebuild\b.*\btest\b", command):
        return "xcodebuild"
    if re.search(r"\bswift\s+test\b", command):
        return "swift"
    # Rust
    if re.search(r"\bcargo\s+test\b", command):
        return "cargo"
    # Java/Kotlin
    if re.search(r"\bmvn\s+test\b", command) or re.search(r"\bmvn\s+verify\b", command):
        return "maven"
    if (
        re.search(r"\bgradle\s+test\b", command)
        or re.search(r"(?:^|[\s/])\.?/gradlew\s+test\b", command)
        or re.search(r"\bgradlew\s+test\b", command)
    ):
        return "gradle"
    # Ruby
    if re.search(r"\brspec\b", command):
        return "rspec"
    if re.search(r"\bruby\s+-Itest\b", command) or re.search(
        r"\brake\s+test\b", command
    ):
        return "minitest"
    # PHP
    if re.search(r"\bphpunit\b", command):
        return "phpunit"
    # C# / .NET
    if re.search(r"\bdotnet\s+test\b", command):
        return "dotnet"
    # Dart/Flutter
    if re.search(r"\bdart\s+test\b", command) or re.search(
        r"\bflutter\s+test\b", command
    ):
        return "dart"
    # Elixir
    if re.search(r"\bmix\s+test\b", command):
        return "elixir"
    # C/C++ (Google Test, CTest)
    if re.search(r"\bctest\b", command):
        return "ctest"
    return None


# ---------------------------------------------------------------------------
# Test result parsing
# ---------------------------------------------------------------------------


def parse_test_results(tool_response: str, framework: str) -> dict:
    """Parse test output. Returns {passed, failed, errors}."""
    result = {"passed": 0, "failed": 0, "errors": 0}

    match framework:
        case "pytest":
            m = re.search(r"(\d+)\s+passed", tool_response)
            if m:
                result["passed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+failed", tool_response)
            if m:
                result["failed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+error", tool_response)
            if m:
                result["errors"] = int(m.group(1))

        case "jest":
            # "Tests:  2 failed, 3 passed, 5 total" or "Tests:  5 passed, 5 total"
            m = re.search(r"(\d+)\s+failed", tool_response)
            if m:
                result["failed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+passed", tool_response)
            if m:
                result["passed"] = int(m.group(1))

        case "go":
            # Count ok lines (passes) and FAIL lines
            result["passed"] = len(re.findall(r"^ok\s+", tool_response, re.MULTILINE))
            result["failed"] = len(
                re.findall(r"^---\s+FAIL:", tool_response, re.MULTILINE)
            )
            if (
                result["passed"] == 0
                and result["failed"] == 0
                and re.search(r"^FAIL\s+", tool_response, re.MULTILINE)
            ):
                result["failed"] = 1

        case "unittest":
            # "Ran 821 tests in 32.346s\n\nOK" or "FAILED (failures=2, errors=1)"
            m = re.search(r"Ran\s+(\d+)\s+tests?", tool_response)
            total = int(m.group(1)) if m else 0
            m = re.search(r"failures=(\d+)", tool_response)
            failures = int(m.group(1)) if m else 0
            m = re.search(r"errors=(\d+)", tool_response)
            errors = int(m.group(1)) if m else 0
            result["failed"] = failures + errors
            result["errors"] = errors
            result["passed"] = max(0, total - result["failed"])

        case "xcodebuild" | "swift":
            # "Executed 5 tests, with 2 failures ..."
            m = re.search(
                r"Executed\s+(\d+)\s+tests?,\s+with\s+(\d+)\s+failures?",
                tool_response,
            )
            if m:
                total = int(m.group(1))
                failures = int(m.group(2))
                result["failed"] = failures
                result["passed"] = max(0, total - failures)

        case "cargo":
            # "test result: ok. 15 passed; 0 failed; 0 ignored"
            m = re.search(r"(\d+)\s+passed", tool_response)
            if m:
                result["passed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+failed", tool_response)
            if m:
                result["failed"] = int(m.group(1))

        case "maven" | "gradle":
            # Maven: "Tests run: 10, Failures: 2, Errors: 1"
            m = re.search(
                r"Tests\s+run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+)",
                tool_response,
            )
            if m:
                total = int(m.group(1))
                failures = int(m.group(2))
                errors = int(m.group(3))
                result["failed"] = failures + errors
                result["errors"] = errors
                result["passed"] = max(0, total - result["failed"])

        case "rspec":
            # "10 examples, 2 failures"
            m = re.search(
                r"(\d+)\s+examples?,\s*(\d+)\s+failures?",
                tool_response,
            )
            if m:
                result["passed"] = max(0, int(m.group(1)) - int(m.group(2)))
                result["failed"] = int(m.group(2))

        case "minitest":
            # "5 runs, 10 assertions, 1 failures, 0 errors"
            m = re.search(
                r"(\d+)\s+runs?,.*?(\d+)\s+failures?,\s*(\d+)\s+errors?",
                tool_response,
            )
            if m:
                total = int(m.group(1))
                failures = int(m.group(2))
                errors = int(m.group(3))
                result["failed"] = failures + errors
                result["errors"] = errors
                result["passed"] = max(0, total - result["failed"])

        case "phpunit":
            # "OK (10 tests, 20 assertions)" or
            # "FAILURES!\nTests: 10, Assertions: 20, Failures: 2"
            m = re.search(r"OK\s+\((\d+)\s+tests?", tool_response)
            if m:
                result["passed"] = int(m.group(1))
            else:
                m = re.search(
                    r"Tests:\s*(\d+).*?Failures:\s*(\d+)",
                    tool_response,
                )
                if m:
                    total = int(m.group(1))
                    failures = int(m.group(2))
                    result["failed"] = failures
                    result["passed"] = max(0, total - failures)

        case "dotnet":
            # "Passed!  - Failed: 0, Passed: 5, Skipped: 0, Total: 5"
            m = re.search(r"Passed:\s*(\d+)", tool_response)
            if m:
                result["passed"] = int(m.group(1))
            m = re.search(r"Failed:\s*(\d+)", tool_response)
            if m:
                result["failed"] = int(m.group(1))

        case "dart":
            # "+5: All tests passed!" or "+3 -2: Some tests failed"
            m = re.search(r"\+(\d+):.*All tests passed", tool_response)
            if m:
                result["passed"] = int(m.group(1))
            else:
                m = re.search(r"\+(\d+)\s+-(\d+)", tool_response)
                if m:
                    result["passed"] = int(m.group(1))
                    result["failed"] = int(m.group(2))

        case "elixir":
            # "10 tests, 2 failures"
            m = re.search(
                r"(\d+)\s+tests?,\s*(\d+)\s+failures?",
                tool_response,
            )
            if m:
                total = int(m.group(1))
                failures = int(m.group(2))
                result["failed"] = failures
                result["passed"] = max(0, total - failures)

        case "ctest":
            # "100% tests passed, 0 tests failed out of 10"
            m = re.search(
                r"(\d+)\s+tests?\s+failed\s+out\s+of\s+(\d+)",
                tool_response,
            )
            if m:
                result["failed"] = int(m.group(1))
                total = int(m.group(2))
                result["passed"] = max(0, total - result["failed"])

        case "vitest":
            # Same format as Jest
            m = re.search(r"(\d+)\s+failed", tool_response)
            if m:
                result["failed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+passed", tool_response)
            if m:
                result["passed"] = int(m.group(1))

        case "bun":
            # "130 pass\n 0 fail" or "130 pass, 0 fail"
            m = re.search(r"(\d+)\s+pass", tool_response)
            if m:
                result["passed"] = int(m.group(1))
            m = re.search(r"(\d+)\s+fail", tool_response)
            if m:
                result["failed"] = int(m.group(1))

    return result
