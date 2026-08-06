#!/usr/bin/env python3
"""Test result parsing — one output shape per framework.

Pure functions, no SMM dependencies. Two siblings do the work either side of
this module: `framework_detect` names the framework from the COMMAND before
the run, `result_counts` pulls the numbers out of the OUTPUT after it. This
module owns only what a count means for each framework.

Extracted from bash_post_tool.py for module size management; the detection
half split off to `framework_detect` when the per-framework summary anchors
landed. `is_test_run` is re-exported below so existing importers and
`mock.patch("...test_parsing.is_test_run")` sites are unaffected.
"""

import re

import result_counts
from framework_detect import is_test_run  # noqa: F401  (re-export)

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

# Summary-line anchors (see `_apply_two_counts`). Each names the ONE line a
# runner puts its counts on, so several sub-runs sum instead of overwriting and
# an echoed count on any other line is simply not a summary.
# The colon is OPTIONAL — jest prints `Tests:  5 passed, 5 total`, vitest
# `      Tests  5 passed (5)`, and both share this arm. Not line-anchored:
# turbo and nx prefix the wrapped runner's line with the package
# (`@acme/api:test:  Tests: 2 failed …`), so requiring a line start silently
# drops every workspace-runner summary. `\bTests\b` cannot match
# "Test Suites:" (which counts FILES, not tests) — that line has a space
# where this needs the plural.
_RE_JEST_SUMMARY = r"\bTests\b:?\s"
_RE_CARGO_SUMMARY = r"\btest result:"
_RE_DOTNET_SUMMARY = r"(?:Passed|Failed|Skipped)!\s*-"
_RE_MOCHA_SUMMARY = r"^\s*\d+\s+(?:passing|failing)\b"


# The frameworks whose whole-response scan is a DECLARED strategy rather than
# the residue of a missing anchor. `playwright` shares the jest arm but prints
# no `Tests:` line of its own; an nx/turbo package running something other than
# jest prints no line either arm can key on. Every other anchored arm resolves
# to no result when its anchor finds nothing, because "this arm did not
# recognise the output" is not "the run reported these counts".
_DELIBERATE_SCAN_FALLBACK = frozenset({"playwright", "nx", "turbo"})


def _apply_two_counts(
    result: dict,
    tool_response: str,
    pass_re: str,
    fail_re: str,
    summary_line: str | None = None,
    scan_fallback: bool = False,
) -> None:
    """Parse counts into result and set status from match outcome.

    matched + non-zero counts → PARSED; matched + zero counts → ZERO
    (the framework's summary line proves it ran with zero tests, even when
    a framework-specific zero marker isn't recognized). Unmatched leaves
    status at the caller's default (PARSER_FAILED) with the counts at zero.

    *summary_line* is a per-framework anchor for runners whose counts sit on an
    identifiable summary line: those are SUMMED across every match, so a run
    that emits one summary per sub-run and no aggregate (cargo's test binaries
    plus its doc-test block, a dotnet solution, a workspace launcher) reports
    the whole run instead of one arbitrary member of it.

    With no anchor the whole-response scan IS the arm's strategy (bun, deno,
    node-test). With one, a miss means no result — UNLESS *scan_fallback* says
    the scan is this framework's declared fallback too. Reading a count out of
    arbitrary text is how a probe that merely MENTIONED a runner was recorded
    as a real zero-passed/three-failed run, so the fallback has to be somebody's
    stated intent, never a consequence of the anchor missing. See
    `result_counts`.
    """
    passed = failed = 0
    matched = False
    if summary_line is None:
        passed, failed, matched = result_counts.two_counts(
            tool_response, pass_re, fail_re
        )
    else:
        passed, failed, matched = result_counts.summary_line_counts(
            tool_response, summary_line, pass_re, fail_re
        )
        if not matched and scan_fallback:
            passed, failed, matched = result_counts.two_counts(
                tool_response, pass_re, fail_re
            )
    result["passed"] = passed
    result["failed"] = failed
    if matched:
        result["status"] = (
            PARSER_STATUS_ZERO if (passed + failed == 0) else PARSER_STATUS_PARSED
        )


def parse_test_results(
    tool_response: str, framework: str, *, allow_scan_fallback: bool = False
) -> dict:
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

    *allow_scan_fallback* opts an anchored arm back into the whole-response
    scan, and exists because the two callers ask different questions of the
    same text. `bash_post_tool` RECORDS a result: with nothing to anchor on it
    must answer "no result", or a command that merely MENTIONED a runner gets
    a recorded count. `test_attribution.parsed_failed_count` ATTRIBUTES an
    already-observed non-zero exit: the failure is evidence it did not
    produce, and it is only deciding whom to blame — so it opts in, and a
    genuinely failing `cd app && <runner>` with an unfamiliar summary still
    files its concern. Strict is the default so the recording caller cannot
    get the permissive answer by omission.
    """
    result = {
        "status": PARSER_STATUS_FAILED,
        "passed": 0,
        "failed": 0,
        "errors": 0,
    }
    # Once, before any arm reads the text. A colour code against the anchor
    # token is invisible to a human and fatal to the regex, and every arm below
    # is exposed — see `result_counts.strip_ansi`.
    tool_response = result_counts.strip_ansi(tool_response)
    scan_fallback = allow_scan_fallback or framework in _DELIBERATE_SCAN_FALLBACK

    match framework:
        case "pytest":
            if re.search(r"\bno tests ran\b|\bcollected 0 items\b", tool_response):
                result["status"] = PARSER_STATUS_ZERO
                return result
            # Every count comes from pytest's OWN summary line, never from the
            # rest of the response. Chained tools share one Bash call and one
            # tool_response (`pytest -q; pyright`), and `errors` folds into
            # `failed` — so a stray "0 errors" from the tool that ran next used
            # to zero the collection errors that were the run's only signal.
            # No summary line, no region, no result — for BOTH reads below.
            # pytest has a summary line in every reporter shape this meets, so
            # its absence means this output is not a pytest run's, however
            # count-shaped the rest of it looks.
            region = result_counts.pytest_summary_region(tool_response)
            if region is None:
                if not scan_fallback:
                    return result
                region = tool_response
            _apply_two_counts(result, region, _RE_N_PASSED, _RE_N_FAILED)
            errors = result_counts.last_count(r"(\d+)\s+error", region)
            if errors is not None:
                result["errors"] = errors
                # Fold errors into failed so consumers see one disjoint
                # "did-not-pass" count — matches unittest/maven/minitest convention.
                result["failed"] += errors
                result["status"] = PARSER_STATUS_PARSED

        case "jest" | "vitest" | "playwright":
            # "Tests:  2 failed, 3 passed, 5 total" or "Tests:  5 passed, 5 total"
            # "No tests found" is the only zero marker that needs its own
            # branch: it carries no counts. A `Tests: 0 passed, 0 total` line
            # does, so the summed path below reaches ZERO on its own — and it
            # must, because a short-circuit on the FIRST such line reported a
            # whole workspace as zero when one package happened to be empty.
            if re.search(r"\bNo tests found\b", tool_response):
                result["status"] = PARSER_STATUS_ZERO
                return result
            # Anchor on the `Tests:` line: it is the one that counts TESTS
            # (`Test Suites:` precedes it and counts files), and a workspace
            # launcher — `pnpm -r test`, `yarn workspaces foreach`, lerna, all
            # of which land in this arm — prints one per package with no
            # aggregate, so the counts have to be summed or a red package is
            # erased by a green one. Playwright has no such line and falls back
            # — deliberately, via `_DELIBERATE_SCAN_FALLBACK`. jest and vitest
            # do have one, so for them a missing anchor is no result at all.
            _apply_two_counts(
                result,
                tool_response,
                _RE_N_PASSED,
                _RE_N_FAILED,
                summary_line=_RE_JEST_SUMMARY,
                scan_fallback=scan_fallback,
            )

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
            # "test result: ok. 15 passed; 0 failed; 0 ignored" — one such line
            # per test binary, plus a trailing Doc-tests block that closes every
            # run. Summed: the doc-tests block contributes its own real counts
            # (usually 0/0), and under --no-fail-fast a red binary is not
            # erased by a green one that ran after it.
            _apply_two_counts(
                result,
                tool_response,
                _RE_N_PASSED,
                _RE_N_FAILED,
                summary_line=_RE_CARGO_SUMMARY,
                scan_fallback=scan_fallback,
            )

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
            # "Passed!  - Failed: 0, Passed: 5, Skipped: 0, Total: 5" — one per
            # project on a solution run, with no aggregate, so they sum.
            _apply_two_counts(
                result,
                tool_response,
                r"Passed:\s*(\d+)",
                r"Failed:\s*(\d+)",
                summary_line=_RE_DOTNET_SUMMARY,
                scan_fallback=scan_fallback,
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
            # "  10 passing (123ms)" and optional "  2 failing", each alone on
            # its line — which is what makes them safe to read. The numbered
            # failure list that follows carries test TITLES, and a title
            # reading "must report 7 failing rows" is indistinguishable from a
            # count in any whole-response scan, first or last.
            _apply_two_counts(
                result,
                tool_response,
                r"(\d+)\s+passing",
                r"(\d+)\s+failing",
                summary_line=_RE_MOCHA_SUMMARY,
                scan_fallback=scan_fallback,
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
            # nx/turbo wrap underlying frameworks, one summary per package and
            # no aggregate line, so the package summaries sum. The jest/vitest
            # `Tests:` anchor covers the common wrapped runner; a package
            # running something else has no line this can key on and falls back
            # to the whole-response scan, which still reports only ONE package.
            # That residue is the recorded multi-sub-run debt, and it is why
            # these two are in `_DELIBERATE_SCAN_FALLBACK`.
            _apply_two_counts(
                result,
                tool_response,
                _RE_N_PASSED,
                _RE_N_FAILED,
                summary_line=_RE_JEST_SUMMARY,
                scan_fallback=scan_fallback,
            )

    return result
