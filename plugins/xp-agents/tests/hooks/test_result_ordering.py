#!/usr/bin/env python3
"""WHICH matches become the recorded count — extraction policy only.

The per-framework shape tests in test_result_parsing.py all feed one clean
summary. Real output is not that: a runner emits several sub-run summaries with
no aggregate, echoes source text or test titles that read like counts, or
shares one Bash call with a second tool. What gets counted then decides whether
the failure gate arms, so it is its own question and gets its own file.

Two strategies are pinned here (see `result_counts`): summing over an anchored
summary LINE, and the whole-response last-match fallback for runners with no
such line.

How several summaries COMBINE is the sibling question, and lives in
`test_result_multi_sub_run.py` — this file is about which text within one
response is authoritative.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import test_parsing


class TestCountsComeFromTheSummaryNotTheNoise(unittest.TestCase):
    """Summary-last runners: the LAST match is the authoritative one.

    Reported live: a Bun suite at 4373 pass / 0 fail recorded `1 failed` and
    filed a high-severity concern that armed the Stop gate, on three separate
    green runs. The number came from a test file whose own source reads "the
    batch must report 1 failed / 1 smsed", echoed back inside bun's error
    context — ahead of the summary, so it won the first-match race.

    Line-anchoring would not fix it — `ok | 5 passed | 2 failed` (deno) and
    `test result: ok. 15 passed; 0 failed` (cargo) are mid-line, so an anchor
    trades a rare false count for a routine blind one.
    """

    _ECHOED_SOURCE = (
        " 4 | // the batch must report 1 failed / 1 smsed\n"
        " 5 |   expect(res.sent).toBe(1)\n"
        " 4373 pass\n"
        " 2 skip\n"
        " 0 fail\n"
    )

    def test_echoed_source_text_does_not_become_the_failure_count(self):
        result = test_parsing.parse_test_results(self._ECHOED_SOURCE, "bun")
        self.assertEqual(result["failed"], 0, "the summary is 0 fail")
        self.assertEqual(result["passed"], 4373)

    def test_a_real_failure_in_the_summary_still_counts(self):
        """The guard must not simply prefer zero.

        Same shape, red summary: taking the last match has to report the
        failure as readily as it ignores the echo, or the fix is a gate that
        can never fire.
        """
        red = self._ECHOED_SOURCE.replace(" 0 fail", " 3 fail")
        result = test_parsing.parse_test_results(red, "bun")
        self.assertEqual(result["failed"], 3)

    def test_a_running_tally_yields_to_the_total(self):
        """Generic shape, not bun-specific: per-file lines then a total.

        Written against the jest arm, which no longer scans — jest HAS a
        summary line, so a response without one is no result there. Playwright
        is the same shape with the scan still in force by design, so the
        last-match policy is pinned where it actually lives.
        """
        output = "spec/a.spec.ts: 2 passed\nspec/b.spec.ts: 3 passed\n5 passed\n"
        result = test_parsing.parse_test_results(output, "playwright")
        self.assertEqual(result["passed"], 5)

    def test_suite_counts_do_not_beat_test_counts(self):
        """Jest prints `Test Suites:` BEFORE `Tests:` — the later line wins."""
        output = (
            "Test Suites: 1 failed, 2 passed, 3 total\n"
            "Tests:       4 failed, 96 passed, 100 total\n"
        )
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["passed"], 96)
        self.assertEqual(result["failed"], 4)


class TestCountsComeFromTheSummaryLine(unittest.TestCase):
    """Anchored runners: every summary line counts, and only summary lines.

    First-vs-last is a false choice for these. Each can emit SEVERAL summaries
    with no aggregate, so any single-match rule reports one sub-run and erases
    the others — last-match hides a red earlier package, first-match hides a
    red later one, and both let text that merely LOOKS like a count win.
    Anchoring on the summary line and summing answers all three.
    """

    def test_mocha_failure_list_does_not_overwrite_the_counts(self):
        """Mocha prints counts, then the numbered failure list with titles."""
        output = (
            "  10 passing (123ms)\n"
            "  1 failing\n\n"
            "  1) Batch\n"
            "       the batch must report 7 failing rows:\n"
            "     AssertionError: expected 0 to equal 7\n"
        )
        result = test_parsing.parse_test_results(output, "mocha")
        self.assertEqual(result["passed"], 10)
        self.assertEqual(result["failed"], 1, "7 came from an echoed title")

    def test_cargo_doc_test_block_does_not_zero_a_green_run(self):
        """`cargo test` always appends a Doc-tests result line, usually 0/0."""
        output = (
            "running 15 tests\n"
            "test result: ok. 15 passed; 0 failed; 0 ignored; 0 measured\n\n"
            "   Doc-tests mycrate\n\nrunning 0 tests\n\n"
            "test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured\n"
        )
        result = test_parsing.parse_test_results(output, "cargo")
        self.assertEqual(result["passed"], 15)
        self.assertEqual(result["status"], "parsed")

    def test_cargo_doc_test_block_does_not_erase_a_real_failure(self):
        """Under --no-fail-fast the doc-test block follows a FAILED binary.

        Reading the last match reports 0 failed for a genuinely red run, so
        no failure concern is filed — a disarmed gate, not a noisy one.
        """
        output = (
            "test result: FAILED. 19 passed; 1 failed; 0 ignored\n\n"
            "   Doc-tests mycrate\n\nrunning 0 tests\n\n"
            "test result: ok. 0 passed; 0 failed; 0 ignored\n"
        )
        result = test_parsing.parse_test_results(output, "cargo")
        self.assertEqual(result["failed"], 1)

    def test_a_green_sub_run_does_not_erase_a_red_one(self):
        """turbo/nx interleave per-package summaries with no aggregate line."""
        output = (
            "@acme/api:test:  Tests: 2 failed, 8 passed, 10 total\n"
            "@acme/web:test:  Tests: 0 failed, 30 passed, 30 total\n"
            " Tasks:    2 successful, 2 total\n"
        )
        result = test_parsing.parse_test_results(output, "turbo")
        self.assertEqual(result["failed"], 2)

    def test_dotnet_sums_every_project_summary(self):
        """A solution run prints one summary per project, no aggregate."""
        output = (
            "Failed!  - Failed: 2, Passed: 8, Skipped: 0, Total: 10\n"
            "Passed!  - Failed: 0, Passed: 30, Skipped: 0, Total: 30\n"
        )
        result = test_parsing.parse_test_results(output, "dotnet")
        self.assertEqual(result["failed"], 2)
        self.assertEqual(result["passed"], 38, "both projects ran")

    def test_pytest_error_count_comes_from_the_summary(self):
        """Errors fold into `failed`, so an echoed count arms the gate."""
        output = (
            "E   AssertionError: the fixture must surface 9 errors\n"
            "=========== 1 failed, 4 passed, 2 errors in 0.42s ===========\n"
        )
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["failed"], 3, "1 failed + 2 errors")


class TestAnAnchoredArmRefusesToGuess(unittest.TestCase):
    """No summary line, no result — for the arms that HAVE a summary line.

    Detection reads the COMMAND, so output from anything that merely MENTIONS
    a runner is routed into that runner's arm. When the anchor then finds
    nothing, the arm has not recognised the output; it has not learned that
    the run reported a count somewhere else. Falling back to the whole-response
    scan there turned a probe's own label into a recorded run of
    zero-passed/three-failed and filed the high-severity concern that arms the
    Stop gate, over a fully green suite.

    Every refusal below is paired, through the same call, with the shape that
    still parses — a parser rewired to return nothing at all would pass the
    refusals on its own.
    """

    # framework -> (real summary, noise a whole-response scan would read a
    # count out of). Each noise line is shaped for that arm's OWN count
    # regexes, so the pairing tests the anchor and not the regex.
    _ANCHORED = (
        (
            "jest",
            "Tests:       2 failed, 3 passed, 5 total\n",
            "step 'must report 3 failed rows' finished\n",
        ),
        (
            "vitest",
            "      Tests  2 failed | 3 passed (5)\n",
            "step 'must report 3 failed rows' finished\n",
        ),
        (
            "cargo",
            "test result: FAILED. 3 passed; 2 failed; 0 ignored\n",
            "step 'must report 3 failed rows' finished\n",
        ),
        (
            "dotnet",
            "Failed!  - Failed: 2, Passed: 3, Skipped: 0, Total: 5\n",
            "step 'must report Failed: 3 rows' finished\n",
        ),
        (
            "mocha",
            "  3 passing (12ms)\n  2 failing\n",
            "step 'must report 3 failing rows' finished\n",
        ),
    )

    def test_no_summary_line_yields_no_result(self):
        for framework, _, noise in self._ANCHORED:
            with self.subTest(framework=framework):
                result = test_parsing.parse_test_results(noise, framework)
                self.assertEqual(result["status"], "parser_failed")
                self.assertEqual(result["failed"], 0)
                self.assertEqual(result["passed"], 0)

    def test_the_same_arm_still_reads_a_real_summary(self):
        for framework, summary, _ in self._ANCHORED:
            with self.subTest(framework=framework):
                result = test_parsing.parse_test_results(summary, framework)
                self.assertEqual(result["status"], "parsed")
                self.assertEqual(result["passed"], 3)
                self.assertEqual(result["failed"], 2)


class TestPytestWithoutItsSummaryLine(unittest.TestCase):
    """The pytest arm is region-scoped in BOTH of its reads, so both skip.

    The region used to widen to the whole response when no summary line was
    found, which is the same guess by another route: a `pytest` in the command
    plus any count-shaped text in the output produced a recorded result. Both
    the pass/fail pair and the separate `N error` read take the region, so a
    region that does not exist has to stop both.
    """

    _SUMMARY = "=========== 1 failed, 4 passed, 2 errors in 0.42s ===========\n"

    def test_counts_are_not_read_without_a_summary_line(self):
        result = test_parsing.parse_test_results(
            "some tool reported 3 failed things\n", "pytest"
        )
        self.assertEqual(result["status"], "parser_failed")
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["passed"], 0)

    def test_errors_are_not_read_without_a_summary_line(self):
        """The `N error` read is a second, separate scan over the region."""
        result = test_parsing.parse_test_results(
            "pyright: 2 errors, 0 warnings, 0 informations\n", "pytest"
        )
        self.assertEqual(result["status"], "parser_failed")
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["failed"], 0)

    def test_a_real_summary_line_still_feeds_both_reads(self):
        """The pairing: refusing is only right if answering still works."""
        result = test_parsing.parse_test_results(self._SUMMARY, "pytest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 4)
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["failed"], 3, "1 failed + 2 errors")


class TestADeliberateFallbackIsKept(unittest.TestCase):
    """Two arms fall back BY DESIGN, and must not inherit the anchored rule.

    `playwright` shares the jest arm but prints no `Tests:` line of its own,
    and an nx/turbo package running something other than jest prints no line
    either arm can key on. For them the whole-response scan is the strategy,
    not the accident — so a missing anchor still has to produce their counts.
    """

    _NO_KEYABLE_LINE = (
        (
            "playwright",
            "Running 5 tests using 2 workers\n\n  2 failed\n  3 passed (12.3s)\n",
        ),
        ("nx", "> nx run api:test\n  3 passed, 2 failed\n"),
        ("turbo", "@acme/api:test:   3 passed, 2 failed\n"),
    )

    def test_the_whole_response_scan_still_answers(self):
        for framework, output in self._NO_KEYABLE_LINE:
            with self.subTest(framework=framework):
                result = test_parsing.parse_test_results(output, framework)
                self.assertEqual(result["status"], "parsed")
                self.assertEqual(result["passed"], 3)
                self.assertEqual(result["failed"], 2)

    def test_deliberate_and_accidental_differ_on_the_same_text(self):
        """The discriminator: identical input, opposite answers.

        This is also the honest record of what the deliberate fallback still
        costs — playwright reads the count out of a label here, exactly as
        jest used to. That residue is the known multi-sub-run/no-anchor debt,
        not something this pin endorses.
        """
        noise = "step 'must report 3 failed rows' finished\n"
        self.assertEqual(
            test_parsing.parse_test_results(noise, "jest")["status"], "parser_failed"
        )
        self.assertEqual(
            test_parsing.parse_test_results(noise, "playwright")["failed"], 3
        )


class TestTextThatMerelyLooksLikeACount(unittest.TestCase):
    """A count is only a count when it is on the runner's summary line."""

    def test_a_mocha_test_title_is_not_a_failure_count(self):
        """The original bun incident, relocated to a runner with no anchor.

        A fully green mocha run prints NO `failing` line at all, so any
        whole-response scan reads the number out of a passing test's TITLE and
        files the high-severity concern that arms the Stop gate on a green
        suite. Neither match ordering helps; only the anchor does.
        """
        output = (
            "  2 passing (12ms)\n\n"
            "  Batch\n"
            "    ✓ the batch must report 7 failing rows\n"
            "    ✓ the batch must report 3 passing rows\n"
        )
        result = test_parsing.parse_test_results(output, "mocha")
        self.assertEqual(result["failed"], 0, "there is no failing line")
        self.assertEqual(result["passed"], 2)

    def test_a_second_tool_in_the_same_bash_call_cannot_zero_the_errors(self):
        """`pytest -q; pyright` shares one command and one tool_response.

        pytest's errors fold into `failed`, so reading the LAST `N error(s)`
        anywhere took pyright's tail instead — zeroing a run whose only failure
        signal was collection errors and promoting it to a clean parse.
        """
        output = (
            "2 errors in 0.42s\n"
            "0 errors, 0 warnings, 0 informations\n"
            "Completed in 1.05sec\n"
        )
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["failed"], 2, "collection errors did not pass")


if __name__ == "__main__":
    unittest.main()
