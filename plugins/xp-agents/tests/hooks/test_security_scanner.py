#!/usr/bin/env python3
"""Tests for security_scanner.py — Pattern, Finding, scan_diff()."""

import dataclasses
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from security_scanner import Finding, Pattern, scan_diff


def _aws_pattern(skip_tests: bool = False) -> Pattern:
    """Helper: a stable AWS-key-shaped Pattern for tests."""
    return Pattern(
        name="aws-access-key",
        regex=re.compile(r"AKIA[0-9A-Z]{16}"),
        skip_tests=skip_tests,
    )


class TestPattern(unittest.TestCase):
    """Pattern dataclass behavior."""

    def test_pattern_is_frozen(self):
        """Pattern is a frozen dataclass — assignment raises."""
        p = _aws_pattern()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            p.name = "renamed"  # type: ignore[misc]

    def test_pattern_default_skip_tests_is_false(self):
        """skip_tests defaults to False so callers must opt in."""
        p = Pattern(name="test", regex=re.compile(r"."))
        self.assertFalse(p.skip_tests)


class TestFinding(unittest.TestCase):
    """Finding dataclass behavior."""

    def test_finding_is_frozen(self):
        """Finding is a frozen dataclass — assignment raises."""
        f = Finding(
            pattern_name="x",
            file_path="a.py",
            line_number=1,
            line_content="content",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            f.line_number = 2  # type: ignore[misc]


class TestScanDiff(unittest.TestCase):
    """scan_diff() core behavior."""

    def test_empty_diff_returns_no_findings(self):
        """A blank diff yields no findings regardless of patterns."""
        self.assertEqual(scan_diff("", [_aws_pattern()]), [])

    def test_added_line_with_match_emits_finding(self):
        """A single + line matching the pattern produces one Finding.

        Hunk header pins the new-file start at line 1, so the assertion
        line_number==1 holds for both the minimal scanner (which reports
        line=1 unconditionally) and the future full hunk parser (which
        will derive line=1 from the +1 in the hunk header).
        """
        diff = (
            "diff --git a/scripts/cfg.py b/scripts/cfg.py\n"
            "--- a/scripts/cfg.py\n"
            "+++ b/scripts/cfg.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].pattern_name, "aws-access-key")
        self.assertEqual(findings[0].file_path, "scripts/cfg.py")
        self.assertEqual(findings[0].line_number, 1)
        self.assertIn("AKIA1234567890ABCDEF", findings[0].line_content)


if __name__ == "__main__":
    unittest.main()
