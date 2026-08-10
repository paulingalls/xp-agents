#!/usr/bin/env python3
"""No `scripts/` file may carry more prose than its recorded ceiling.

Per file, in absolute lines. The measurement and the slack live separately in
`_prose_baseline`, which exposes only the ceiling; this asserts the tree
against it, and proves the tolerance is spendable in one direction and bounded
in the other.

WHAT THIS IS NOT. It covers one shipped root, not all three — Milestone 4 is
the all-roots ratchet.

And it is a WEAK proxy for the pass that earned it. That pass's real output was
claims corrected against the code, and a claim can be narrowed to a true one
without moving any number here. Green means no file's prose outgrew its
ceiling. It does not mean prose shrank, and it does not mean prose is TRUE —
whether a claim still matches its code is a reviewer's judgment, and whether
the test a claim points at still exists is `test_prose_pointer_pin`'s.

The real-tree assertion below is green by construction the moment anything is
deleted, so it says nothing about whether the comparison works.
`_prose_violations` exists to be driven with synthetic tables where the red
state is reachable — the same reason `test_file_size_pin.py` takes an
injectable ceilings table.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _pin_helpers import rel
from _prose_baseline import PROSE_MEASURED, PROSE_SLACK_LINES, prose_ceilings
from _prose_scan import scan_roots

_PLUGIN_ROOT = Path(__file__).parent.parent
_REPO_ROOT = _PLUGIN_ROOT.parent.parent

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
#
# WHAT IT COSTS, IN THE UNIT PROSE IS WRITTEN IN. The 102 files under the floor
# held ~6,700 lines of headroom between them on 2026-08-10, so `scripts/` prose
# could grow by about half again before anything here reddens. This is a
# per-FILE regrowth check, not a tree-wide budget; the ratio it replaced was the
# reverse of that trade and fired falsely twice, which is why the trade was made.
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


class TestScriptsProseStaysUnderItsCeilings(unittest.TestCase):
    def _scanned(self) -> dict[str, int]:
        root = scan_roots(_PLUGIN_ROOT)["scripts"]

        self.assertGreater(len(root.files), 0, "scan found no files in scripts/")
        self.assertEqual(root.parse_failures, ())
        return {
            rel(f.path, _REPO_ROOT): f.docstring_lines + f.comment_lines
            for f in root.files
        }

    def test_no_scripts_file_exceeds_its_recorded_ceiling(self):
        self.assertEqual(_prose_violations(self._scanned(), prose_ceilings()), [])

    def test_every_recorded_ceiling_still_names_a_file_in_the_tree(self):
        """A stale entry silently shrinks what the check above covers, and a
        table that drifted to nothing would report clean over an empty set."""
        self.assertEqual(sorted(PROSE_MEASURED.keys() - self._scanned().keys()), [])

    def _governed(self) -> dict[str, int]:
        """The scanned files a ceiling actually governs.

        Both slack proofs below grow this population, never the whole scan. A
        file BELOW the floor reddens by crossing it, which is the floor's rule
        and not the slack's — folding those in makes the red proof pass on
        evidence that says nothing about the allowance, and makes the headroom
        proof fail the day an ordinary file lands three lines under the floor.
        """
        return {
            p: n
            for p, n in self._scanned().items()
            if n > _PROSE_FLOOR and p in PROSE_MEASURED
        }

    def test_the_governed_population_is_not_vacuous(self):
        """A floor set above every file would make this pin certify nothing."""
        governed = [n for n in self._scanned().values() if n > _PROSE_FLOOR]

        self.assertGreaterEqual(
            len(governed),
            30,
            "expected the floor to govern a substantial share of scripts/ — "
            "if it governs almost nothing, the ceilings certify almost nothing",
        )

    def test_the_tree_has_room_for_a_rationale_comment(self):
        """Why the slack exists: three added rationale lines in every governed
        file is the edit this milestone produces, and must not fail at push."""
        grown = {path: n + 3 for path, n in self._governed().items()}

        self.assertEqual(_prose_violations(grown, prose_ceilings()), [])

    def test_the_tree_plus_a_systematic_regrowth_is_red(self):
        """A slack large enough never to fire is worse than no pin, so the RED
        state is proved on the real tree at its real distance from the ceiling:
        one line past the allowance, in every governed file, must fail.

        EVERY one, not merely some: a count short of the population means some
        ceiling absorbed the extra line, which is the amnesty this asserts
        against."""
        governed = self._governed()
        grown = {path: n + PROSE_SLACK_LINES + 1 for path, n in governed.items()}

        self.assertEqual(len(_prose_violations(grown, prose_ceilings())), len(governed))


class TestTheDeclaredSlack(unittest.TestCase):
    def test_the_ceiling_is_the_measurement_plus_the_declared_slack(self):
        """Both halves stay separately readable: a future reader can see what
        was observed and what is being tolerated, not one fudged number."""
        ceilings = prose_ceilings()

        self.assertEqual(ceilings.keys(), PROSE_MEASURED.keys())
        for path, measured in PROSE_MEASURED.items():
            self.assertEqual(ceilings[path], measured + PROSE_SLACK_LINES)

    def test_the_slack_is_an_allowance_not_an_amnesty(self):
        """Small against the floor itself. Past that a governed file could grow
        by a whole rationale paragraph before anything noticed, and
        `test_the_tree_plus_a_systematic_regrowth_is_red` is the behavioural
        half of the same bound."""
        self.assertLess(PROSE_SLACK_LINES, _PROSE_FLOOR // 10)


if __name__ == "__main__":
    unittest.main()
