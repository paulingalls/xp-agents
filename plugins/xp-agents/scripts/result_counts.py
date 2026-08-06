#!/usr/bin/env python3
"""Numeric count extraction for test-runner output.

The layer under `test_parsing`'s per-framework arms. Pure functions, stdlib
only (re); no status vocabulary — the caller owns what a count MEANS.

Two strategies, and the framework arm picks:

`summary_line_counts` — anchor on the runner's summary LINE and SUM across
every one found. This is the correct shape whenever a run can produce several
sub-runs with no aggregate line: cargo prints one `test result:` per test
binary plus a trailing doc-test block, a dotnet solution prints one per
project, and a workspace launcher (`pnpm -r test`, turbo, nx) prints one per
package. Any single-match rule reports ONE of them and erases the rest —
first-match hides a red later package, last-match hides a red earlier one, and
the second is the dangerous direction because it disarms the failure gate on a
red suite. Summing reports the run. The anchor also keeps counts echoed from
source text or a failure title out of the total, since an echo is not on a
summary line.

`two_counts` — whole-response scan, LAST match wins. The fallback for runners
whose summary is not line-identifiable (bun, deno, playwright, node-test).
Last, because there the summary trails the noise: live, a file whose own source
read "the batch must report 1 failed" was echoed inside bun's error context and
beat the `0 fail` summary on a green run. It is a fallback, not a policy — it
still reports a single sub-run when a runner emits several.

Both scan lazily (`re.search`/`re.finditer`), never `findall`: a tool response
runs to 10 MB and only one match is ever used.
"""

import re


def _first(pattern: str, text: str) -> int | None:
    """The first numeric match of *pattern* in *text*, or None."""
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _last(pattern: str, text: str) -> int | None:
    """The last numeric match of *pattern* in *text*, or None.

    `finditer`, not `findall`: a tool response runs to 10 MB and only the final
    match is ever used, so nothing is materialized along the way.
    """
    found = None
    for match in re.finditer(pattern, text):
        found = match
    return int(found.group(1)) if found else None


def two_counts(tool_response: str, pass_re: str, fail_re: str) -> tuple[int, int, bool]:
    """Two counts from the whole response, last match wins.

    Returns (passed, failed, matched); an absent count reads 0 but does not on
    its own set *matched*.
    """
    p = _last(pass_re, tool_response)
    f = _last(fail_re, tool_response)
    return p or 0, f or 0, p is not None or f is not None


def summary_line_counts(
    tool_response: str, line_re: str, pass_re: str, fail_re: str
) -> tuple[int, int, bool]:
    """Two counts summed over every line matching *line_re*.

    Returns (passed, failed, matched). *matched* is False when no anchored
    line carried a count at all — the caller falls back rather than recording
    a zero, because "the anchor did not fit this output" and "the run had zero
    tests" are different answers.
    """
    anchor = re.compile(line_re)
    passed = 0
    failed = 0
    matched = False
    for line in tool_response.splitlines():
        if not anchor.search(line):
            continue
        p = _first(pass_re, line)
        f = _first(fail_re, line)
        if p is None and f is None:
            continue
        matched = True
        passed += p or 0
        failed += f or 0
    return passed, failed, matched


# pytest's summary line, across `-q` and the default reporter: a count token
# AND the run duration, on one line. Both halves are load-bearing. The `=`
# fencing alone is not enough (`-q` drops it); the count alone is not enough
# either — that is exactly how a second tool in the same Bash call (`pytest -q;
# pyright`) got its "0 errors" read as pytest's error count, zeroing the
# collection errors that were the run's only failure signal.
_PYTEST_COUNT = re.compile(
    r"\b\d+\s+(?:passed|failed|error|skipped|xfailed|xpassed|deselected)"
)
_PYTEST_DURATION = re.compile(r"\bin\s+[\d.]+\s*s")


def pytest_summary_region(tool_response: str) -> str:
    """pytest's own summary line, or the whole response when none is found.

    Falling back to the whole response keeps a reporter shape this does not
    recognize parseable — a narrower answer than the caller had before, never
    a blind one.
    """
    region = None
    for line in tool_response.splitlines():
        if _PYTEST_COUNT.search(line) and _PYTEST_DURATION.search(line):
            region = line
    return tool_response if region is None else region


def last_count(pattern: str, text: str) -> int | None:
    """The last numeric match, or None. Public for single-count callers."""
    return _last(pattern, text)
