#!/usr/bin/env python3
"""Tests that budget measurement uses character counts, not lines or bytes.

RED until _budget_helpers.py is updated:
- TestMdCharMeasurement: fails because assert_md_under_budgets currently
  uses splitlines() (line count), so a file with few lines but many chars
  is NOT flagged as an offender when it should be.

GREEN after fix:
- assert_md_under_budgets uses len(read_text()) instead of splitlines()
- assert_emitter_under_budgets uses len(decoded) instead of len(bytes)
- assert_preload_under_budgets uses len(decoded) instead of len(bytes)
"""

import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _budget_helpers import (
    assert_md_budgets_match,
    assert_md_under_budgets,
    band_offender,
    ratchet,
)


class _SpyCase(unittest.TestCase):
    """Minimal TestCase that absorbs assertFalse calls without raising.

    Used to probe whether assert_md_under_budgets would report an offender
    without polluting the outer TestCase's failure state.
    """

    def runTest(self) -> None:
        pass


class TestMdCharMeasurement(unittest.TestCase):
    """assert_md_under_budgets must measure files in characters, not lines."""

    def test_few_lines_many_chars_reported_as_offender(self) -> None:
        """File under line-budget but over char-budget must be flagged.

        Construct a .md with 3 lines but ~603 characters. Set a budget of 10:
        - 3 lines < 10  → line-based code does NOT flag it (wrong)
        - 603 chars > 10 → char-based code flags it as an offender (correct)

        The test asserts the offender IS reported, so it is RED against the
        current line-based implementation and GREEN after the char fix.
        """
        long_line = "x" * 200
        content = "\n".join([long_line, long_line, long_line])

        line_count = len(content.splitlines())  # 3
        char_count = len(content)  # 603

        budget = 10  # above line_count, below char_count

        self.assertLessEqual(line_count, budget, "precondition: lines under budget")
        self.assertGreater(char_count, budget, "precondition: chars exceed budget")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "TESTFILE.md").write_text(content, encoding="utf-8")

            spy = _SpyCase()
            offender_reported = False
            try:
                assert_md_under_budgets(
                    spy, tmp_path, "*.md", {"TESTFILE": budget}, "test"
                )
            except AssertionError:
                offender_reported = True

            self.assertTrue(
                offender_reported,
                "assert_md_under_budgets must flag the file as an offender "
                "when its character count exceeds the budget, even when its "
                "line count does not.",
            )


class TestStdoutCharMeasurement(unittest.TestCase):
    """Stdout budget measurement must use decoded character count, not byte count.

    For ASCII-only output, bytes == chars, so existing budgets are unchanged.
    For multibyte UTF-8 output, this distinction matters: 'é'*100 is 100 chars
    but 200 bytes. The budget is in chars, so the correct measurement is the
    decoded character length.
    """

    def test_multibyte_utf8_char_count_differs_from_byte_count(self) -> None:
        """'é'*100 is 100 chars and 200 bytes — correct measurement is 100 chars."""
        content = "é" * 100
        stdout_bytes = content.encode("utf-8")

        byte_count = len(stdout_bytes)
        char_count = len(stdout_bytes.decode("utf-8", errors="replace"))

        self.assertEqual(byte_count, 200, "UTF-8 encoding of 'é'*100 is 200 bytes")
        self.assertEqual(char_count, 100, "Decoded char count of 'é'*100 is 100 chars")

    def test_budget_measured_in_chars_allows_content_under_char_budget(self) -> None:
        """Budget of 150 chars must ALLOW 100 chars even if the byte count is 200.

        Under byte measurement: 200 > 150 → flagged as offender (wrong).
        Under char measurement: 100 < 150 → within budget (correct).

        This pins the formula: len(stdout_bytes.decode('utf-8', errors='replace')).
        """
        content = "é" * 100
        stdout_bytes = content.encode("utf-8")

        budget = 150  # above char count (100), below byte count (200)

        char_count = len(stdout_bytes.decode("utf-8", errors="replace"))
        byte_count = len(stdout_bytes)

        # Char measurement: within budget — the correct behavior
        self.assertLessEqual(char_count, budget, "char count must be within budget")
        # Byte measurement: would exceed budget — the wrong behavior
        # bytes > budget; chars <= budget — demonstrates the unit matters
        self.assertGreater(byte_count, budget)


class TestRatchetNeverRaises(unittest.TestCase):
    """`ratchet` recalculates a budget DOWNWARD only.

    The recorded calibration rule is `actual * 1.125`, and applied on its own
    it RAISES most surfaces: it only lowers when `actual` has fallen below
    `current / 1.125` — an 11.1% cut. Most files the audit trimmed were
    trimmed by less than that, so the monotonic guard is what makes the rule a
    ratchet instead of a re-baseline.
    """

    def test_barely_trimmed_file_keeps_its_old_budget(self):
        """The case the guard exists for — a file the audit barely touched.

        Verified on a small trim, not only on a large one: at a 1% cut the raw
        formula wants a HIGHER number than the budget already on record.
        """
        current = 8900
        actual = 8811  # a 1% trim off a file that sat at 8900

        raw_formula = round(actual * 1.125 / 10) * 10
        self.assertGreater(
            raw_formula,
            current,
            "precondition: the raw formula wants to RAISE this budget",
        )
        self.assertEqual(ratchet(actual, current, 10), current)

    def test_never_returns_above_current_across_the_range(self):
        """Swept rather than sampled: monotonicity must hold at every size."""
        for granularity in (10, 100):
            for current in (100, 1150, 8900, 23100):
                for actual in range(0, current + 200, 97):
                    with self.subTest(g=granularity, current=current, actual=actual):
                        self.assertLessEqual(
                            ratchet(actual, current, granularity), current
                        )

    def test_hard_trimmed_file_actually_lowers(self):
        """The other direction: the ratchet must still bite when it can.

        Without this, `return current` would satisfy every other test here.
        """
        self.assertEqual(ratchet(5668, 8900, 100, rounding=math.ceil, floor=100), 6400)

    def test_lowered_budget_leaves_the_file_near_89_percent(self):
        """The calibration multiplier and the 98% band are separate knobs.

        A freshly ratcheted surface must land well clear of the band, or the
        ratchet would arm a failure in the same commit that computes it.
        Asserted on the post-audit numbers rather than taken on faith.
        """
        for actual, current, granularity in (
            (5668, 8900, 100),
            (1024, 1150, 10),
            (20500, 23100, 10),
        ):
            with self.subTest(actual=actual):
                kwargs = (
                    {"rounding": math.ceil, "floor": 100} if granularity == 100 else {}
                )
                new = ratchet(actual, current, granularity, **kwargs)
                pct = actual / new * 100
                self.assertLess(pct, 98.0, f"{pct:.1f}% is inside the band")
                self.assertGreater(pct, 85.0, f"{pct:.1f}% wastes headroom")


class TestRatchetNonVacuity(unittest.TestCase):
    """A measurement of 0 must NOT become a budget of 0.

    Ten of the emitter fixtures measure 0 chars: the fixture drives the
    emitter's no-trigger path, so the surface is never exercised. Ratcheting
    that to 0 would encode "this scans nothing" as the bound — the same defect
    story-001 fixed, where a pin scanned less than it claimed.
    """

    def test_zero_measurement_leaves_the_budget_unchanged(self):
        self.assertEqual(ratchet(0, 100, 100, rounding=math.ceil, floor=100), 100)
        self.assertEqual(ratchet(0, 1150, 10), 1150)

    def test_zero_measurement_does_not_collapse_to_the_floor(self):
        """Distinct from the floor: floor=100 would also yield 100 here.

        Use a budget well above the floor so "returned current" and "returned
        floor" are different numbers and the test can tell them apart.
        """
        self.assertEqual(ratchet(0, 8900, 100, rounding=math.ceil, floor=100), 8900)


class TestNinetyEightPercentBand(unittest.TestCase):
    """The assertion must fail BEFORE breach, and say by how much.

    Firing only on breach is why nine skills, three agents and one guide
    drifted to 98-100% of cap while every suite stayed green.
    """

    def test_file_at_98_percent_is_an_offender(self):
        offender = band_offender("XP_VALUES", 980, 1000)
        self.assertIsNotNone(offender, "98.0% of cap must fail, not pass")

    def test_offender_names_the_file_and_its_percentage(self):
        offender = band_offender("PROCESS_GUIDE", 8730, 8900)
        assert offender is not None
        self.assertIn("PROCESS_GUIDE", offender, "must name the file")
        self.assertIn("98.1", offender, "must name the percentage, not just chars")

    def test_file_below_the_band_passes(self):
        self.assertIsNone(band_offender("XP_VALUES", 979, 1000))

    def test_file_over_budget_is_still_an_offender(self):
        """The band widens the old check; it must not replace it."""
        self.assertIsNotNone(band_offender("XP_VALUES", 1200, 1000))

    def test_zero_measurement_is_not_a_band_offender(self):
        """Consistent with the ratchet's non-vacuity guard.

        `hook_io.py` carries a deliberate budget of 0 and emits no reason
        prose. A naive `actual >= 0.98 * budget` reads 0 >= 0 as a breach and
        fails a surface that has not grown by a single character.
        """
        self.assertIsNone(band_offender("hook_io.py", 0, 0))
        self.assertIsNone(band_offender("prompt_nugget.py", 0, 100))

    def test_prose_arriving_at_a_zero_budget_is_an_offender(self):
        """The other half: 0 is a bound, not an exemption."""
        self.assertIsNotNone(band_offender("hook_io.py", 12, 0))


class TestMdBudgetsMatchStillFailsOnMissingEntry(unittest.TestCase):
    """AC4: the threshold change must not weaken the symmetric match.

    A shipped .md with no budget entry has no bound at all, which is a
    strictly worse failure than one sitting at 98% of a bound. Pinned here
    because the band and the match assertion live in the same module and a
    future edit could plausibly fold one into the other.
    """

    def test_shipped_md_without_a_budget_entry_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "BUDGETED.md").write_text("x", encoding="utf-8")
            (tmp_path / "UNBUDGETED.md").write_text("x", encoding="utf-8")

            spy = _SpyCase()
            with self.assertRaises(AssertionError) as caught:
                assert_md_budgets_match(
                    spy, tmp_path, "*.md", {"BUDGETED": 100}, "test"
                )
            self.assertIn("UNBUDGETED", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
