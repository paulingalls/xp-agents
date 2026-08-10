#!/usr/bin/env python3
"""The materially-short margin's boundary, and what each branch may say.

`test_lint_config_style_flags.TestBatchTimeoutMarginIsNotABareLessThan` already
covers the two sides of the margin at half and five times its width. Neither
fixture lands ON the boundary, so a `>=` weakened to `>` survives both; the
first class here is the case that kills it.

The second class covers the branch asymmetry: a hang carries the caller's
remedy, and deliberately does not carry the shared-budget clause.
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import lint_budget


def _expired(seconds: float) -> subprocess.TimeoutExpired:
    return subprocess.TimeoutExpired(["ruff", "check"], seconds)


class TestMarginBoundaryIsInclusive(unittest.TestCase):
    """`consumed == own_ceiling - _MATERIALLY_SHORT_S` reads as a hang.

    The docstring's claim is that a consumed duration materially BELOW the
    ceiling reads as cut short, and one at or near it still reads as a hang.
    "At" is the boundary itself, and only a fixture sitting exactly on it
    distinguishes `>=` from `>`. Derived from the constant, never a literal:
    a hardcoded 35.0 would stop testing the boundary the moment either
    constant moved.
    """

    _CEILING = lint_budget.own_ceiling_s(40)

    def _at_boundary(self) -> float:
        boundary = self._CEILING - lint_budget._MATERIALLY_SHORT_S
        self.assertLess(
            boundary,
            self._CEILING,
            "a zero-width margin would make this test prove nothing",
        )
        return boundary

    def test_exactly_on_the_boundary_reads_as_a_hang(self):
        consumed = self._at_boundary()
        message = lint_budget.timeout_message(
            "ruff",
            _expired(consumed),
            timeout=consumed,
            own_ceiling=self._CEILING,
            budget_s=None,
        )
        self.assertIn("timed out after", message)
        self.assertNotIn("cut short", message)

    def test_one_hair_below_the_boundary_reads_as_cut_short(self):
        consumed = self._at_boundary() - 0.01
        message = lint_budget.timeout_message(
            "ruff",
            _expired(consumed),
            timeout=consumed,
            own_ceiling=self._CEILING,
            budget_s=None,
        )
        self.assertIn("may have been cut short rather than hung", message)
        self.assertNotIn("timed out after", message)


class TestHangCarriesRemedyButNotBudget(unittest.TestCase):
    """A hang states the remedy; it does not state the starting budget.

    The remedy the stdin path offers — re-stage the file so it lints in the
    shared batch instead of costing a process of its own — is what the
    operator can act on, and a process that hangs needs it as much as one that
    was cut short. `budget_s` is different: it reports what was left of the
    shared budget when this run STARTED, which explains a squeezed slice and
    explains nothing about a run that then spent its whole ceiling.
    """

    _CEILING = lint_budget.own_ceiling_s(1)
    _REMEDY = "`git add app.ts` lets it lint in the shared batch instead"

    def _hang_message(self) -> str:
        return lint_budget.timeout_message(
            "eslint",
            _expired(self._CEILING),
            timeout=self._CEILING,
            own_ceiling=self._CEILING,
            budget_s=self._CEILING - 0.5,
            remedy=self._REMEDY,
        )

    def test_the_fixture_really_is_on_the_hang_side(self):
        """Guards the pair below: on the cut-short side they prove nothing."""
        self.assertIn("timed out after", self._hang_message())

    def test_hang_states_the_remedy(self):
        self.assertIn(self._REMEDY, self._hang_message())

    def test_hang_omits_the_starting_budget_clause(self):
        self.assertNotIn("shared lint budget", self._hang_message())


if __name__ == "__main__":
    unittest.main()
