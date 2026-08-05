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


class TestASubRunIsNeverErasedByAnother(unittest.TestCase):
    """One summary per sub-run and no aggregate — so they sum.

    The failure mode all of these share: a run whose sub-runs disagree gets
    recorded as whichever one the extraction happened to land on. When that is
    a GREEN one, no failure concern is filed and the resolver records the red
    suite as passing — the gate is disarmed, not merely noisy.
    """

    def test_cargo_does_not_report_only_the_first_test_binary(self):
        """A green lib binary must not hide a red integration binary."""
        output = (
            "test result: ok. 12 passed; 0 failed; 0 ignored\n\n"
            "     Running tests/integration.rs\n"
            "test result: FAILED. 3 passed; 2 failed; 0 ignored\n\n"
            "   Doc-tests mycrate\n"
            "test result: ok. 0 passed; 0 failed; 0 ignored\n"
        )
        result = test_parsing.parse_test_results(output, "cargo")
        self.assertEqual(result["failed"], 2, "the second binary was red")
        self.assertEqual(result["passed"], 15, "12 + 3 across both binaries")

    def test_a_workspace_launcher_does_not_report_only_one_package(self):
        """`pnpm -r test` and friends resolve to the jest arm.

        Every npm/pnpm/yarn/lerna script alias lands there, and those are
        exactly the multi-package/no-aggregate shape — the same one the
        workspace task runners have. A red package must survive a green one
        whichever order they print in.
        """
        red_first = (
            "Tests:       2 failed, 8 passed, 10 total\n"
            "Tests:       0 failed, 30 passed, 30 total\n"
        )
        for output in (red_first, "".join(reversed(red_first.splitlines(True)))):
            with self.subTest(order=output.splitlines()[0]):
                result = test_parsing.parse_test_results(output, "jest")
                self.assertEqual(result["failed"], 2)
                self.assertEqual(result["passed"], 38)

    def test_vitest_prints_its_counts_without_a_colon(self):
        """vitest shares the jest arm but not jest's `Tests:` punctuation.

        Its default reporter prints `      Tests  5 passed (5)` — indented,
        no colon — so an anchor spelled `Tests:` never matches and the arm
        falls back to the whole-response scan, silently reporting one package
        of a workspace. `is_test_run` routes vitest here, and turbo/nx
        wrapping vitest land in the same place.
        """
        output = (
            " Test Files  1 passed (1)\n"
            "      Tests  30 passed (30)\n"
            " Test Files  1 failed (1)\n"
            "      Tests  2 failed | 6 passed (8)\n"
        )
        result = test_parsing.parse_test_results(output, "vitest")
        self.assertEqual(result["failed"], 2)
        self.assertEqual(
            result["passed"],
            36,
            "both packages must be summed — the fallback scan reports only "
            "the last line it happens to see",
        )

    def test_one_empty_package_does_not_zero_the_whole_workspace(self):
        """The zero marker short-circuited on the FIRST `0 passed, 0 total`.

        A workspace where one package has no tests is ordinary, and it used to
        return ZERO for the entire run — recording 0 tests for a suite that ran
        30. The summed path reaches ZERO on its own when everything is zero, so
        the marker was never needed for count-bearing lines.
        """
        output = "Tests:       0 passed, 0 total\nTests:       30 passed, 30 total\n"
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["passed"], 30)


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
