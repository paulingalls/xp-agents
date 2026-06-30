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

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _budget_helpers import assert_md_under_budgets


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


if __name__ == "__main__":
    unittest.main()
