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
leave the ratio untouched. Green means prose did not outgrow CODE — the measure
is a ratio, so added code buys headroom for added prose. It does not mean prose
shrank, and it does not mean prose is true.

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
from _prose_baseline import (
    BASELINE_FILES,
    BASELINE_PROSE,
    BASELINE_TOTAL,
    measure_named,
    missing_from,
)
from _prose_scan import scan_roots

_PLUGIN_ROOT = Path(__file__).parent.parent


def _ratio_regression(
    prose: int, total: int, base_prose: int, base_total: int
) -> str | None:
    """A message when `prose/total` is not strictly below the baseline ratio.

    Cross-multiplied rather than divided — integer comparison has no rounding
    to argue about, and a zero `total` would otherwise raise instead of
    reporting.

    Both denominators are guarded, not just the measured one: a zero
    *base_total* makes every measurement "below" the baseline, so a mistyped
    constant would disable the pin without failing.
    """
    if total <= 0:
        return f"no lines measured at all ({total}) — the scan found nothing"
    if base_total <= 0:
        return (
            f"baseline is unusable ({base_prose}/{base_total}) — "
            "nothing to compare against"
        )
    if prose * base_total > base_prose * total:
        now = prose / total * 100
        was = base_prose / base_total * 100
        return (
            f"scripts prose ratio is {now:.2f}% ({prose}/{total}), "
            f"not below its recorded {was:.2f}% ({base_prose}/{base_total})"
        )
    return None


class TestTheBaselineFileSet(_AssertNotNoneMixin, unittest.TestCase):
    """The set is what makes the two numbers comparable at all.

    A ratio measured over one set of files says nothing about a different set.
    Both defects this pin shipped with were that mismatch: a file EXTRACTED out
    of another (which CLAUDE.md's 500-line rule demands) arrives carrying a
    module docstring and no code the tree did not already have, so it raises the
    ratio while nothing rotted.
    """

    def test_a_file_outside_the_baseline_set_is_not_measured(self):
        """The extraction case, which is what reddened this pin: a new file
        made entirely of prose must not move a number recorded before it
        existed."""
        measured = measure_named(
            {"kept.py": (10, 100), "extracted.py": (80, 80)}, {"kept.py"}
        )

        self.assertEqual(measured, (10, 100))

    def test_growth_inside_the_baseline_set_still_counts(self):
        """The exemption must not become a hole: prose added to a file the
        baseline DID measure is the regrowth this pin exists to catch."""
        measured = measure_named({"kept.py": (40, 100)}, {"kept.py"})

        self.assertEqual(measured, (40, 100))
        self.assertIsNotNone(_ratio_regression(*measured, 10, 100))

    def test_a_vanished_baseline_file_is_reported_not_silently_dropped(self):
        """Shrinking the set silently shrinks what the pin measures, and a set
        that has drifted to nothing would measure 0/0 and read as clean."""
        self.assertEqual(
            missing_from({"kept.py": (10, 100)}, {"kept.py", "gone.py"}), ("gone.py",)
        )

    def test_a_set_that_still_matches_the_tree_reports_nothing_missing(self):
        self.assertEqual(missing_from({"kept.py": (10, 100)}, {"kept.py"}), ())


class TestTheRatioComparisonItself(_AssertNotNoneMixin, unittest.TestCase):
    """Synthetic numbers, because the real tree can only ever be green here."""

    def test_measuring_exactly_the_baseline_is_clean(self):
        """A RATCHET's compliant state is sitting AT its recorded number — the
        pin no longer has to prove a sweep improved things (that happened, and
        is in history), only that the number does not climb."""
        self.assertIsNone(_ratio_regression(12602, 31422, 12602, 31422))

    def test_one_prose_line_above_the_baseline_is_a_regression(self):
        """The RED state, and the reason equality had to stay clean rather than
        the comparison being dropped: the margin is still exact."""
        self.assertIsNotNone(_ratio_regression(12603, 31422, 12602, 31422))

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

    def test_a_zero_baseline_is_reported_not_silently_passed(self):
        """A baseline of zero makes every measurement 'below' it. Guarding only
        the measured side would let a mistyped constant disable the pin."""
        self.assertIsNotNone(_ratio_regression(12602, 31422, 12602, 0))

    def test_the_message_names_both_ratios(self):
        message = self._assert_not_none(_ratio_regression(60, 100, 50, 100))

        self.assertIn("60.00%", message)
        self.assertIn("50.00%", message)


class TestScriptsProseStaysBelowItsBaseline(unittest.TestCase):
    def _scanned(self) -> dict[str, tuple[int, int]]:
        root = scan_roots(_PLUGIN_ROOT)["scripts"]

        self.assertGreater(len(root.files), 0, "scan found no files in scripts/")
        self.assertEqual(root.parse_failures, ())
        return {
            f.path.name: (f.docstring_lines + f.comment_lines, f.total_lines)
            for f in root.files
        }

    def test_every_baseline_file_still_exists(self):
        """A name whose file is gone stops being measured, and the pin would
        report clean on a set quietly smaller than the one it was recorded
        over. Re-record both the set and the numbers instead."""
        self.assertEqual(missing_from(self._scanned(), BASELINE_FILES), ())

    def test_the_shipped_scripts_root_is_below_its_recorded_ratio(self):
        prose, total = measure_named(self._scanned(), BASELINE_FILES)

        self.assertIsNone(
            _ratio_regression(prose, total, BASELINE_PROSE, BASELINE_TOTAL)
        )


if __name__ == "__main__":
    unittest.main()
