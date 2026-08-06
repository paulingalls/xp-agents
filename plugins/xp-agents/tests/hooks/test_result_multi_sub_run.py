#!/usr/bin/env python3
"""One Bash call, several sub-runs, no aggregate — so the counts SUM.

Split from `test_result_ordering.py`, which was 20 lines short of the band
floor with these cases still arriving: the repo's rule is to extract rather
than ratchet. Ordering (first vs last match) and summing are two questions
anyway — ordering decides which text is authoritative within ONE summary,
summing decides how several summaries combine.

The failure mode every case here shares: a run whose sub-runs disagree is
recorded as whichever one the extraction happened to land on. When that is a
GREEN one, no failure concern is filed and a red suite is recorded as passing —
the gate is disarmed, not merely noisy.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

import test_parsing


class TestASubRunIsNeverErasedByAnother(unittest.TestCase):
    """One summary per sub-run and no aggregate — so they sum."""

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

    def test_a_countless_empty_package_does_not_zero_the_whole_workspace(self):
        """The same erasure through the OTHER zero marker, which carries no
        counts of its own and so short-circuited ahead of the summed path.

        `pnpm -r test` over a workspace where one package has no test files at
        all: jest exits non-zero with `No tests found` and prints no `Tests:`
        line, while the package that DID run printed a red one. Returning zero
        for the whole run recorded `test_passed` with no failure concern, and
        the three real failures reached nothing.
        """
        output = (
            "Tests:       3 failed, 12 passed, 15 total\n"
            "No tests found, exiting with code 1\n"
        )
        result = test_parsing.parse_test_results(output, "jest")
        self.assertEqual(result["status"], "parsed")
        self.assertEqual(result["failed"], 3, "the package that ran was red")
        self.assertEqual(result["passed"], 12)

    def test_pytest_does_not_report_only_the_last_sub_run(self):
        """`pytest tests/unit; pytest tests/integration` is ONE Bash call.

        pytest prints one summary line per invocation and no aggregate, so
        reading only the last one reported 0 failed for a red run — and the
        shell's exit status is the LAST command's, so the success path was
        taken, no failure concern was filed, and the Stop gate never armed.
        """
        output = (
            "======== 3 failed, 10 passed in 2.10s =========\n"
            "============= 40 passed in 5.30s ==============\n"
        )
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["failed"], 3, "the first invocation was red")
        self.assertEqual(result["passed"], 50, "10 + 40 across both invocations")

    def test_pytest_sums_the_errors_of_every_sub_run(self):
        """Errors fold into `failed`, so the second read has to sum too."""
        output = (
            "======== 1 failed, 2 errors in 2.10s =========\n"
            "============= 3 errors in 5.30s ==============\n"
        )
        result = test_parsing.parse_test_results(output, "pytest")
        self.assertEqual(result["errors"], 5, "2 + 3 across both invocations")
        self.assertEqual(result["failed"], 6, "1 failed + 5 errors")


if __name__ == "__main__":
    unittest.main()
