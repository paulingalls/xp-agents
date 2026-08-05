#!/usr/bin/env python3
"""Which regex match is the authoritative count — ordering policy only.

The count regexes scan the WHOLE tool response, so when a payload contains
several matches, ordering decides what gets recorded and whether the failure
gate arms. That policy is per-framework, so it gets its own file rather than
living among the per-framework shape tests in test_result_parsing.py.
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
        """Generic shape, not bun-specific: per-file lines then a total."""
        output = "src/a.test.ts: 2 passed\nsrc/b.test.ts: 3 passed\n5 passed\n"
        result = test_parsing.parse_test_results(output, "jest")
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


class TestSummaryIsNotAlwaysLast(unittest.TestCase):
    """Summary-first runners: the FIRST match is the authoritative one.

    These print their counts BEFORE trailing text that also matches the count
    regexes. Reading the last match moves the phantom-count bug rather than
    fixing it — and for cargo and the workspace runners it moves it in the
    disarming direction, which is the worse one.
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

    def test_dotnet_reads_the_first_project_summary(self):
        """A solution run prints one summary per project, no aggregate."""
        output = (
            "Failed!  - Failed: 2, Passed: 8, Skipped: 0, Total: 10\n"
            "Passed!  - Failed: 0, Passed: 30, Skipped: 0, Total: 30\n"
        )
        result = test_parsing.parse_test_results(output, "dotnet")
        self.assertEqual(result["failed"], 2)

    def test_pytest_error_count_comes_from_the_summary(self):
        """Errors fold into `failed`, so an echoed count arms the gate."""
        output = (
            "E   AssertionError: the fixture must surface 9 errors\n"
            "=========== 1 failed, 4 passed, 2 errors in 0.42s ===========\n"
        )
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["errors"], 2)
        self.assertEqual(result["failed"], 3, "1 failed + 2 errors")


if __name__ == "__main__":
    unittest.main()
