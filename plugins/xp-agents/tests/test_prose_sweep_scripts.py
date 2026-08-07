#!/usr/bin/env python3
"""The `scripts/` prose ratio must not climb back above its pre-sweep number.

Milestone 2's sweep half needs a number that fails if the work is undone. This
records the ratio measured before the verification pass and asserts the tree
stays under it.

WHAT THIS IS NOT. It is not the ratchet — that is a later milestone's
deliverable, recorded at the achieved numbers across all three shipped roots.
This pins one root against one moment.

And it is a WEAK proxy for the pass that earned it. The pass's real output was
claims corrected against the code; narrowing a false claim to a true one can
leave the ratio untouched. A green check here means prose did not regrow, not
that prose is true.

The real-tree assertion below is green by construction the moment anything is
deleted, so it says nothing about whether the comparison works.
`_ratio_regression` exists to be tested against synthetic numbers where the
red state is reachable — the same reason `test_file_size_pin.py` takes an
injectable ceilings table.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _bases import _AssertNotNoneMixin
from _prose_scan import scan_roots

_PLUGIN_ROOT = Path(__file__).parent.parent

# Measured with `_prose_scan.py --root scripts` at story start, before the
# close/review verification pass. Integers, not a rounded percentage: the
# comparison is exact and a percentage would need a tolerance nobody can
# justify.
BASELINE_PROSE = 12602
BASELINE_TOTAL = 31422


def _ratio_regression(
    prose: int, total: int, base_prose: int, base_total: int
) -> str | None:
    """A message when `prose/total` is not strictly below the baseline ratio.

    Cross-multiplied rather than divided — integer comparison has no rounding
    to argue about, and a zero `total` would otherwise raise instead of
    reporting.
    """
    if total <= 0:
        return f"no lines measured at all ({total}) — the scan found nothing"
    if prose * base_total >= base_prose * total:
        now = prose / total * 100
        was = base_prose / base_total * 100
        return (
            f"scripts prose ratio is {now:.2f}% ({prose}/{total}), "
            f"not below its recorded {was:.2f}% ({base_prose}/{base_total})"
        )
    return None


class TestTheRatioComparisonItself(_AssertNotNoneMixin, unittest.TestCase):
    """Synthetic numbers, because the real tree can only ever be green here."""

    def test_the_unswept_baseline_is_a_regression(self):
        """The RED state: measuring exactly the baseline is not an improvement.
        This is what the real-tree assertion returned before the pass ran."""
        self.assertIsNotNone(_ratio_regression(12602, 31422, 12602, 31422))

    def test_a_higher_ratio_is_a_regression(self):
        self.assertIsNotNone(_ratio_regression(60, 100, 50, 100))

    def test_a_lower_ratio_is_clean(self):
        self.assertIsNone(_ratio_regression(40, 100, 50, 100))

    def test_one_prose_line_below_the_baseline_is_clean(self):
        """The margin is exact, not approximate — a single deleted line counts."""
        self.assertIsNone(_ratio_regression(12601, 31421, 12602, 31422))

    def test_a_measurement_of_nothing_is_a_regression_not_a_pass(self):
        """A scan that found no files must not read as a clean tree."""
        self.assertIsNotNone(_ratio_regression(0, 0, 12602, 31422))

    def test_the_message_names_both_ratios(self):
        message = self._assert_not_none(_ratio_regression(60, 100, 50, 100))

        self.assertIn("60.00%", message)
        self.assertIn("50.00%", message)


class TestScriptsProseStaysBelowItsBaseline(unittest.TestCase):
    def test_the_shipped_scripts_root_is_below_its_recorded_ratio(self):
        root = scan_roots(_PLUGIN_ROOT)["scripts"]
        prose = root.docstring_lines + root.comment_lines

        self.assertGreater(len(root.files), 0, "scan found no files in scripts/")
        self.assertEqual(root.parse_failures, ())
        self.assertIsNone(
            _ratio_regression(prose, root.total_lines, BASELINE_PROSE, BASELINE_TOTAL)
        )


if __name__ == "__main__":
    unittest.main()
