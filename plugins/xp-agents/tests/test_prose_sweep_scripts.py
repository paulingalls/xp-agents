#!/usr/bin/env python3
"""The `scripts/` prose ratio must not climb past a measurement plus its slack.

Milestone 2's sweep half needs a number that fails if the work is undone. The
measurement, the file set it was taken over, and the growth deliberately
tolerated on top of it all live in `_prose_baseline`; this asserts the tree
against them, and proves the tolerance is spendable in one direction and
bounded in the other.

WHAT THIS IS NOT. It covers one shipped root, not all three, and pins a ratio
rather than any per-file number.

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
    MEASURED_PROSE,
    MEASURED_TOTAL,
    SLACK_PROSE_LINES,
    measure_named,
    missing_from,
    ratchet_ceiling,
)
from _prose_scan import scan_roots

_PLUGIN_ROOT = Path(__file__).parent.parent

# Prose lines a file may carry before it needs a recorded ceiling. Below it a
# file is ungoverned by RULE — the same uniform exemption for every file —
# rather than by omission from a hand-kept list, which is what let two files
# (`session_start_banner.py`, `run_attribution.py`) sit unmeasured indefinitely.
# Growth is still caught at the crossing: a file that passes this line with no
# recorded ceiling is a violation, so the floor sets where explicit ceilings
# begin, not where enforcement does.
#
# 120 governs 42 of 144 `scripts/` files and 57% of the root's prose lines.
# Lower buys coverage at the cost of reddening most new modules on arrival —
# measured at 60, roughly three in five recently-added files would have had to
# record a ceiling before their first commit, and friction paid that routinely
# stops being read.
_PROSE_FLOOR = 120


def _prose_violations(files: dict[str, int], ceilings: dict[str, int]) -> list[str]:
    """Per-file prose lines that exceed, or fail to declare, a ceiling.

    `files` and `ceilings` are both keyed by repo-relative path. Modelled on
    `test_file_size_pin._band_violations`: the TREE drives the loop and the
    table only supplies numbers, so a file above the floor with no entry is a
    violation rather than an exemption.
    """
    violations = []
    for path, prose in sorted(files.items()):
        if prose <= _PROSE_FLOOR:
            continue
        ceiling = ceilings.get(path)
        if ceiling is None:
            violations.append(
                f"{path} ({prose} prose lines) crossed above {_PROSE_FLOOR} with "
                "no recorded ceiling in _prose_baseline.PROSE_MEASURED"
            )
        elif prose > ceiling:
            violations.append(
                f"{path} grew to {prose} prose lines, above its recorded "
                f"ceiling of {ceiling}"
            )
    return violations


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

        self.assertIsNone(_ratio_regression(prose, total, *ratchet_ceiling()))

    def test_the_tree_plus_a_systematic_regrowth_is_red(self):
        """A slack large enough never to fire is worse than no pin, so the RED
        state is proved on the real tree at its real distance from the ceiling:
        one comment line added to each of the measured files must still fail.

        Comment lines add to BOTH sides of the ratio, so this is not the same
        number as the slack — it is what the slack buys, in the unit prose is
        actually written in."""
        prose, total = measure_named(self._scanned(), BASELINE_FILES)
        added = len(BASELINE_FILES)

        self.assertIsNotNone(
            _ratio_regression(prose + added, total + added, *ratchet_ceiling())
        )

    def test_the_tree_has_room_for_a_rationale_comment(self):
        """And the reason the slack exists: three comment lines with no added
        code is the edit this milestone produces, and must not be a push-time
        failure."""
        prose, total = measure_named(self._scanned(), BASELINE_FILES)

        self.assertIsNone(_ratio_regression(prose + 3, total + 3, *ratchet_ceiling()))


class TestTheDeclaredSlack(unittest.TestCase):
    def test_the_ceiling_is_the_measurement_plus_the_declared_slack(self):
        """Both halves stay separately readable: a future reader can see what
        was observed and what is being tolerated, not one fudged number."""
        self.assertEqual(
            ratchet_ceiling(), (MEASURED_PROSE + SLACK_PROSE_LINES, MEASURED_TOTAL)
        )

    def test_the_slack_is_an_allowance_not_an_amnesty(self):
        """Under 1% of the measured prose. Past that the ratchet stops being a
        ratchet, and `test_the_tree_plus_a_systematic_regrowth_is_red` is the
        behavioural half of the same bound."""
        self.assertLess(SLACK_PROSE_LINES, MEASURED_PROSE // 100)


class TestPerFileProseViolations(unittest.TestCase):
    """Per-file absolute, replacing the ratio above.

    A ratio lets one file's honest shrink pay for another's growth, and moves
    against claim-narrowing — a true claim is usually longer than the false
    short one it replaces. Per-file absolute has neither property.

    `ceilings` is a required argument rather than a table with a sentinel
    default: the only real-tree caller passes the exposed ceilings explicitly,
    so a default would exist purely to be overridden.
    """

    _ABOVE = _PROSE_FLOOR + 10

    def test_growth_past_a_recorded_ceiling_is_flagged(self):
        violations = _prose_violations({"a.py": self._ABOVE}, {"a.py": self._ABOVE - 1})

        self.assertEqual(len(violations), 1)
        self.assertIn("a.py", violations[0])
        self.assertIn(str(self._ABOVE), violations[0])

    def test_sitting_exactly_at_the_ceiling_is_clean(self):
        """A ratchet's compliant state is sitting AT its recorded number."""
        self.assertEqual(
            _prose_violations({"a.py": self._ABOVE}, {"a.py": self._ABOVE}), []
        )

    def test_a_file_above_the_floor_with_no_ceiling_is_flagged(self):
        """The reverse direction, structural: the tree drives the loop and the
        table only supplies numbers, so a file nobody recorded is red by
        construction rather than exempt until someone notices."""
        violations = _prose_violations({"new.py": self._ABOVE}, {})

        self.assertEqual(len(violations), 1)
        self.assertIn("no recorded ceiling", violations[0])

    def test_a_file_below_the_floor_is_not_governed(self):
        self.assertEqual(_prose_violations({"small.py": _PROSE_FLOOR}, {}), [])

    def test_shrinking_to_the_floor_is_allowed_despite_a_higher_ceiling(self):
        """Shrinking leaves the governed population entirely — the early exit,
        not a comparison. A stale ceiling left behind is inert."""
        self.assertEqual(
            _prose_violations({"a.py": _PROSE_FLOOR}, {"a.py": _PROSE_FLOOR * 3}), []
        )

    def test_one_files_shrink_cannot_mask_anothers_growth(self):
        """The defect the ratio had: a sum lets a deletion pay for a regrowth."""
        violations = _prose_violations(
            {"grew.py": self._ABOVE, "shrank.py": _PROSE_FLOOR + 1},
            {"grew.py": self._ABOVE - 5, "shrank.py": self._ABOVE * 2},
        )

        self.assertEqual(len(violations), 1)
        self.assertIn("grew.py", violations[0])


if __name__ == "__main__":
    unittest.main()
