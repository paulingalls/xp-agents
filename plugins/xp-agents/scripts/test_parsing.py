#!/usr/bin/env python3
"""Test framework detection and result parsing.

Pure functions for identifying test commands and parsing their output.
No SMM dependencies — stdlib only (re).

Extracted from bash_post_tool.py for module size management.
"""

import re

# ---------------------------------------------------------------------------
# Command classification
# ---------------------------------------------------------------------------

# Bounded lazy-quantifier "0-5 intervening tokens" — the upper bound keeps
# regex engines from backtracking pathologically on long arg lists.
_FLAG_GAP = r"(?:\s+\S+){0,5}?"
# Reject characters that would extend `test` into a different identifier.
# Includes `.` (file extensions: `bun build test.ts` shouldn't match `test`),
# `-` (kebab tool names: `pnpm exec test-fixture-builder`), and word chars
# (script names: scripts already capture via the colon-suffix group).
_NOT_IDENT_TAIL = r"(?![\w.-])"
# Allow colon-suffixed script names: test, test:unit, test:e2e-live (hyphens
# allowed within the suffix for kebab-case scripts).
_TEST_SCRIPT_TAIL = r"test(?::[\w:-]+)?" + _NOT_IDENT_TAIL

# Package-script / workspace launcher patterns — the test target lives in
# package.json/config, NOT on the command line. Named once so is_test_run and
# is_script_alias_run share one source of truth (a divergence would re-open the
# verify-path gap that script aliases must map to the whole-tree sentinel).
_TURBO_RE = (
    r"\b(?:npx\s+|bunx\s+|pnpm\s+|yarn\s+|bun\s+x\s+)?turbo"
    + _FLAG_GAP
    + r"\s+(?:run\s+)?"
    + _TEST_SCRIPT_TAIL
)
_NX_RES = (
    r"\bnx\s+test\b",
    r"\bnx\s+run\s+\S+:test\b",
    r"\bnx\s+\S+\s+--targets?=test(?:[,\s]|$)",
)
_BUN_SCRIPT_RE = r"\bbun" + _FLAG_GAP + r"\s+(?:run\s+)?" + _TEST_SCRIPT_TAIL
_NPM_SCRIPT_RE = (
    r"\b(?:npm|pnpm|yarn|lerna)" + _FLAG_GAP + r"\s+(?:run\s+)?" + _TEST_SCRIPT_TAIL
)


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
    # Playwright — check before generic script aliases; covers
    # `playwright test`, `npx/bunx/pnpm-exec/yarn playwright test`, and
    # `./node_modules/.bin/playwright test` (\b matches at `/`).
    if re.search(r"\bplaywright\s+test\b", command):
        return "playwright"

    # Direct runners. `\b` already matches at `/` boundaries, so a single
    # word-bounded match covers bare invocation, npx/bunx/pnpm-exec/yarn-dlx
    # wrappers, and direct-binary path tails (`./node_modules/.bin/jest`).
    if re.search(r"\bjest\b", command):
        return "jest"
    if re.search(r"\bvitest\b", command):
        return "vitest"
    if re.search(r"\bmocha\b", command):
        return "mocha"

    # Node built-in test runner: `node --test`, `node --test test/**/*.js`
    if re.search(r"\bnode\s+--test\b", command):
        return "node-test"
    # Deno test runner: `deno test`, `deno test src/`
    if re.search(r"\bdeno\s+test\b", command):
        return "deno"

    # Workspace task runners (turbo). Check turbo before bun/pnpm so that
    # `pnpm turbo test` returns "turbo" rather than the pnpm-script form.
    # Turbo accepts `turbo test`, `turbo run test`, with or without a
    # wrapping `npx`/`bunx`/`pnpm`. `--filter=<pkg>` and other flags may
    # appear after `test`.
    if re.search(_TURBO_RE, command):
        return "turbo"

    # nx workspace runner: `nx test <pkg>`, `nx run <pkg>:test`,
    # `nx run-many --target=test`, `nx run-many --targets=test,build`.
    if any(re.search(p, command) for p in _NX_RES):
        return "nx"

    # bun: bare `bun test[:script]` or `bun run test[:script]`, and the
    # workspace form `bun --filter <pkg> test[:script]` (and similar
    # flag-tolerant variants up to 5 intervening tokens).
    if re.search(_BUN_SCRIPT_RE, command):
        return "bun"

    # npm/pnpm/yarn/lerna script aliases — flag-tolerant (covers --filter,
    # --workspace, -w, -F, -r, workspace foreach, workspace <pkg>, run, etc.)
    # bound to 5 intervening tokens. lerna folded in here since it shares
    # the script-alias shape (`lerna run test [--scope=<pkg>]`).
    if re.search(_NPM_SCRIPT_RE, command):
        return "jest"

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
    # Java/Kotlin — flag-tolerant for monorepo/multi-module forms like
    # `mvn -pl <module> test`, `mvn -pl <module> verify`.
    if re.search(r"\bmvn" + _FLAG_GAP + r"\s+(?:test|verify)\b", command):
        return "maven"
    # Gradle accepts `gradle test`, `./gradlew test`, `./gradlew :module:test`,
    # `./gradlew :module:sub:test` (path-prefixed task name). `\bgradlew\b`
    # subsumes both `./gradlew` and bare `gradlew` invocations.
    if re.search(
        r"\b(?:gradle|gradlew)" + _FLAG_GAP + r"\s+(?::?[\w:-]+:)?test\b",
        command,
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

# Tristate values for parse_test_results()["status"] and the matching
# metadata.parser_status field on test_run_complete events. Imported by
# bash_post_tool to avoid stringly-typed coupling between producer and
# consumer.
PARSER_STATUS_PARSED = "parsed"
PARSER_STATUS_ZERO = "zero"
PARSER_STATUS_FAILED = "parser_failed"

# Shared "N <token>" regexes — used by pytest, jest/vitest/playwright (passed/
# failed) and parameterized for cargo, dotnet, bun.
_RE_N_PASSED = r"(\d+)\s+passed"
_RE_N_FAILED = r"(\d+)\s+failed"


def _parse_two_counts(
    tool_response: str, pass_re: str, fail_re: str
) -> tuple[int, int, bool]:
    """Extract two named numeric counts. Returns (passed, failed, matched)."""
    passed = 0
    failed = 0
    matched = False
    m = re.search(pass_re, tool_response)
    if m:
        passed = int(m.group(1))
        matched = True
    m = re.search(fail_re, tool_response)
    if m:
        failed = int(m.group(1))
        matched = True
    return passed, failed, matched


def _apply_two_counts(
    result: dict, tool_response: str, pass_re: str, fail_re: str
) -> None:
    """Parse counts into result and set status from match outcome.

    matched + non-zero counts → PARSED; matched + zero counts → ZERO
    (the framework's summary line proves it ran with zero tests, even when
    a framework-specific zero marker isn't recognized). Unmatched leaves
    status at the caller's default (PARSER_FAILED).
    """
    passed, failed, matched = _parse_two_counts(tool_response, pass_re, fail_re)
    result["passed"] = passed
    result["failed"] = failed
    if matched:
        result["status"] = (
            PARSER_STATUS_ZERO if (passed + failed == 0) else PARSER_STATUS_PARSED
        )


def parse_test_results(tool_response: str, framework: str) -> dict:
    """Parse test output. Returns {status, passed, failed, errors}.

    status is one of PARSER_STATUS_PARSED / _ZERO / _FAILED:
      - PARSED        — count regex(es) matched
      - ZERO          — framework-specific zero-tests marker matched
      - FAILED        — nothing recognized

    Precedence: framework-specific zero markers first (pytest/jest/vitest/
    playwright/unittest), then numeric regexes via `_apply_two_counts` which
    treats matched-but-zero counts as ZERO (long-tail bistate fallback);
    unmatched leaves status at PARSER_FAILED. `errors` is folded into `failed`
    in every framework so consumers see a single disjoint "did-not-pass"
    count.
    """
    result = {
        "status": PARSER_STATUS_FAILED,
        "passed": 0,
        "failed": 0,
        "errors": 0,
    }

    match framework:
        case "pytest":
            if re.search(r"\bno tests ran\b|\bcollected 0 items\b", tool_response):
                result["status"] = PARSER_STATUS_ZERO
                return result
            _apply_two_counts(result, tool_response, _RE_N_PASSED, _RE_N_FAILED)
            m = re.search(r"(\d+)\s+error", tool_response)
            if m:
                errors = int(m.group(1))
                result["errors"] = errors
                # Fold errors into failed so consumers see one disjoint
                # "did-not-pass" count — matches unittest/maven/minitest convention.
                result["failed"] += errors
                result["status"] = PARSER_STATUS_PARSED

        case "jest" | "vitest" | "playwright":
            # "Tests:  2 failed, 3 passed, 5 total" or "Tests:  5 passed, 5 total"
            # Zero markers: "Tests: ... 0 passed, 0 total" or "No tests found".
            if re.search(
                r"Tests:\s*0\s+passed,\s*0\s+total|\bNo tests found\b",
                tool_response,
            ):
                result["status"] = PARSER_STATUS_ZERO
                return result
            _apply_two_counts(result, tool_response, _RE_N_PASSED, _RE_N_FAILED)

        case "go":
            # Count ok lines (passes) and FAIL lines. Go has no distinct
            # "no tests" output — `ok` with empty package looks identical to
            # truly empty input — so we never claim ZERO here.
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
            if result["passed"] > 0 or result["failed"] > 0:
                result["status"] = PARSER_STATUS_PARSED

        case "unittest":
            # "Ran 821 tests in 32.346s\n\nOK" or "FAILED (failures=2, errors=1)"
            m = re.search(r"Ran\s+(\d+)\s+tests?", tool_response)
            if not m:
                return result
            total = int(m.group(1))
            if total == 0:
                result["status"] = PARSER_STATUS_ZERO
                return result
            m_f = re.search(r"failures=(\d+)", tool_response)
            failures = int(m_f.group(1)) if m_f else 0
            m_e = re.search(r"errors=(\d+)", tool_response)
            errors = int(m_e.group(1)) if m_e else 0
            result["failed"] = failures + errors
            result["errors"] = errors
            result["passed"] = max(0, total - result["failed"])
            result["status"] = PARSER_STATUS_PARSED

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
                result["status"] = PARSER_STATUS_PARSED

        case "cargo":
            # "test result: ok. 15 passed; 0 failed; 0 ignored"
            _apply_two_counts(result, tool_response, _RE_N_PASSED, _RE_N_FAILED)

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
                result["status"] = PARSER_STATUS_PARSED

        case "rspec":
            # "10 examples, 2 failures"
            m = re.search(
                r"(\d+)\s+examples?,\s*(\d+)\s+failures?",
                tool_response,
            )
            if m:
                result["passed"] = max(0, int(m.group(1)) - int(m.group(2)))
                result["failed"] = int(m.group(2))
                result["status"] = PARSER_STATUS_PARSED

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
                result["status"] = PARSER_STATUS_PARSED

        case "phpunit":
            # "OK (10 tests, 20 assertions)" or
            # "FAILURES!\nTests: 10, Assertions: 20, Failures: 2"
            m = re.search(r"OK\s+\((\d+)\s+tests?", tool_response)
            if m:
                result["passed"] = int(m.group(1))
                result["status"] = PARSER_STATUS_PARSED
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
                    result["status"] = PARSER_STATUS_PARSED

        case "dotnet":
            # "Passed!  - Failed: 0, Passed: 5, Skipped: 0, Total: 5"
            _apply_two_counts(
                result, tool_response, r"Passed:\s*(\d+)", r"Failed:\s*(\d+)"
            )

        case "dart":
            # "+5: All tests passed!" or "+3 -2: Some tests failed"
            m = re.search(r"\+(\d+):.*All tests passed", tool_response)
            if m:
                result["passed"] = int(m.group(1))
                result["status"] = PARSER_STATUS_PARSED
            else:
                m = re.search(r"\+(\d+)\s+-(\d+)", tool_response)
                if m:
                    result["passed"] = int(m.group(1))
                    result["failed"] = int(m.group(2))
                    result["status"] = PARSER_STATUS_PARSED

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
                result["status"] = PARSER_STATUS_PARSED

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
                result["status"] = PARSER_STATUS_PARSED

        case "bun":
            # "130 pass\n 0 fail" or "130 pass, 0 fail"
            _apply_two_counts(result, tool_response, r"(\d+)\s+pass", r"(\d+)\s+fail")

        case "mocha":
            # "  10 passing (123ms)" and optional "  2 failing"
            _apply_two_counts(
                result,
                tool_response,
                r"(\d+)\s+passing",
                r"(\d+)\s+failing",
            )

        case "node-test":
            # TAP-ish summary: "# pass N" / "# fail N" / "# tests N"
            _apply_two_counts(
                result, tool_response, r"#\s*pass\s+(\d+)", r"#\s*fail\s+(\d+)"
            )

        case "deno":
            # "ok | 5 passed | 2 failed" (Deno test summary line)
            _apply_two_counts(
                result, tool_response, r"(\d+)\s+passed", r"(\d+)\s+failed"
            )

        case "nx" | "turbo":
            # nx/turbo wrap underlying frameworks; their summary lines vary.
            # Best-effort: fall through to the same N passed/N failed shape
            # that jest/vitest/pytest also use.
            _apply_two_counts(result, tool_response, _RE_N_PASSED, _RE_N_FAILED)

    return result
