#!/usr/bin/env python3
"""Tests for free-function helpers in `_close_fixtures.py`."""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _close_fixtures import _assert_text_ordering

_TESTS_ROOT = Path(__file__).parent
# Distinctive tell of the inline find+assertGreater(-1)+assertLess triplet
# the helper replaces: `self.assertLess(<name>_idx, <other>_idx, ...)`.
# Other assertLess shapes (timing budgets, expr.start(), etc.) don't match.
_TRIPLET_TELL = re.compile(r"assertLess\(\s*\w+_idx\s*,\s*\w+_idx\b")


class TestAssertTextOrdering(unittest.TestCase):
    def test_two_markers_in_order_passes(self):
        text = "alpha then beta"
        _assert_text_ordering(self, text, "alpha", "beta")

    def test_three_markers_in_order_passes(self):
        text = "first second third"
        _assert_text_ordering(self, text, "first", "second", "third")

    def test_out_of_order_pair_fails_with_named_pair(self):
        text = "second comes before first"
        with self.assertRaises(AssertionError) as cm:
            _assert_text_ordering(self, text, "first", "second")
        msg = str(cm.exception)
        self.assertIn("first", msg)
        self.assertIn("second", msg)

    def test_missing_marker_fails_naming_marker(self):
        text = "only alpha here"
        with self.assertRaises(AssertionError) as cm:
            _assert_text_ordering(self, text, "alpha", "missing")
        self.assertIn("missing", str(cm.exception))

    def test_returns_indices_for_caller_reuse(self):
        text = "alpha beta gamma"
        indices = _assert_text_ordering(self, text, "alpha", "beta", "gamma")
        expected = [text.find("alpha"), text.find("beta"), text.find("gamma")]
        self.assertEqual(indices, expected)

    def test_caller_msg_appended_when_provided(self):
        text = "second first"
        with self.assertRaises(AssertionError) as cm:
            _assert_text_ordering(self, text, "first", "second", msg="step-order pin")
        self.assertIn("step-order pin", str(cm.exception))

    def test_fewer_than_two_markers_raises_value_error(self):
        """Concern dd7d1811d4b1: defensive guard at len(markers)<2 had no
        coverage. The helper is meaningless with 0 or 1 markers — fail loud.
        Both boundaries pinned (0 and 1) so the `<` predicate can't mutate
        to `==` undetected."""
        with self.assertRaises(ValueError):
            _assert_text_ordering(self, "alpha")
        with self.assertRaises(ValueError):
            _assert_text_ordering(self, "alpha", "alpha")


class TestNoInlineTextOrderingTriplets(unittest.TestCase):
    """Vocab pin: no `assertLess(<a>_idx, <b>_idx, ...)` shape remains
    in tests/. The text-ordering helper owns this pattern; a regression
    here means a future test re-introduced the inline triplet that this
    story consolidated.
    """

    def test_no_inline_triplets_in_tests_tree(self):
        # Cover both test_*.py and _*.py fixture files — the latter were
        # the original M-2 site (`_close_fixtures.py`), so a future
        # regression there would re-introduce the pattern this story
        # eliminated.
        offenders: list[str] = []
        for path in (*_TESTS_ROOT.rglob("test_*.py"), *_TESTS_ROOT.rglob("_*.py")):
            if path.name == Path(__file__).name:
                continue
            for lineno, line in enumerate(path.read_text().splitlines(), start=1):
                if _TRIPLET_TELL.search(line):
                    rel = path.relative_to(_TESTS_ROOT)
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertFalse(
            offenders,
            "Inline find+assertGreater(-1)+assertLess triplet detected — "
            "use _close_fixtures._assert_text_ordering instead.\n"
            + "\n".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
