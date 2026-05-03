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

        Hunk header pins the new-file start at +1, so line_number==1.
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

    def test_no_pattern_match_returns_no_findings(self):
        """A diff with content that no pattern matches produces no Findings."""
        diff = "+++ b/scripts/safe.py\n@@ -0,0 +1,1 @@\n+x = 1  # safe code\n"
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_removed_line_with_match_emits_no_finding(self):
        """A '-' line containing a secret-shape is not a Finding (it's leaving)."""
        diff = '+++ b/scripts/cfg.py\n@@ -1,1 +1,0 @@\n-key = "AKIA1234567890ABCDEF"\n'
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_context_line_with_match_emits_no_finding(self):
        """A ' ' (context) line containing a secret-shape is not a Finding."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -1,2 +1,2 @@\n"
            ' key = "AKIA1234567890ABCDEF"\n'
            "+x = 1\n"
        )
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_hunk_line_numbering_offset(self):
        """When hunk starts at +5, the first + line is reported at line 5."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -1,3 +5,3 @@\n"
            " context_a\n"
            " context_b\n"
            '+key = "AKIA1234567890ABCDEF"\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line_number, 7)  # 5 + 2 context lines

    def test_hunk_without_count_treated_as_one(self):
        """`@@ -3 +5 @@` (no comma) is a valid one-line hunk; +5 still parses."""
        diff = '+++ b/scripts/cfg.py\n@@ -3 +5 @@\n+key = "AKIA1234567890ABCDEF"\n'
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line_number, 5)

    def test_minus_lines_dont_advance_new_line_counter(self):
        """A '-' line is a removal — new-file line numbers don't advance over it."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -1,3 +1,2 @@\n"
            "-old_line_one\n"
            "-old_line_two\n"
            '+key = "AKIA1234567890ABCDEF"\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line_number, 1)

    def test_multiple_hunks_reset_line_counter(self):
        """Each hunk header re-establishes the new-file line counter."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -1,1 +1,1 @@\n"
            '+key1 = "AKIA1111111111111111"\n'
            "@@ -50,1 +50,1 @@\n"
            '+key2 = "AKIA2222222222222222"\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].line_number, 1)
        self.assertEqual(findings[1].line_number, 50)

    def test_multiple_files_in_one_diff(self):
        """Two files in the same diff each get their own Findings."""
        diff = (
            "+++ b/scripts/a.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key_a = "AKIA1111111111111111"\n'
            "diff --git a/scripts/b.py b/scripts/b.py\n"
            "+++ b/scripts/b.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key_b = "AKIA2222222222222222"\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].file_path, "scripts/a.py")
        self.assertEqual(findings[1].file_path, "scripts/b.py")


class TestEdgeCases(unittest.TestCase):
    """scan_diff() edge cases and defensive behavior."""

    def test_new_file_diff_processes_added_lines(self):
        """`--- /dev/null` followed by `+++ b/new.py` is a new file — scan it."""
        diff = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+secret = "AKIA1234567890ABCDEF"\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].file_path, "new.py")

    def test_deleted_file_diff_emits_nothing(self):
        """`+++ /dev/null` is a deletion — there are no + lines to scan."""
        diff = (
            "diff --git a/old.py b/old.py\n"
            "deleted file mode 100644\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,1 +0,0 @@\n"
            '-key = "AKIA1234567890ABCDEF"\n'
        )
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_binary_file_marker_does_not_crash(self):
        """`Binary files differ` lines are tolerated, not treated as content."""
        diff = (
            "diff --git a/img.png b/img.png\n"
            "Binary files a/img.png and b/img.png differ\n"
        )
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_diff_without_file_header_emits_nothing(self):
        """Without a `+++ b/<path>` header, no file context exists — no findings."""
        diff = '@@ -0,0 +1,1 @@\n+key = "AKIA1234567890ABCDEF"\n'
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])


class TestNoqaSuppression(unittest.TestCase):
    """`# noqa: secret` per-line suppression marker."""

    def test_noqa_secret_suppresses_match(self):
        """A line marked `# noqa: secret` is not reported even if it matches."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"  # noqa: secret\n'
        )
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_noqa_case_insensitive(self):
        """Uppercase `# NOQA: secret` also suppresses."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"  # NOQA: secret\n'
        )
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_noqa_compact_form(self):
        """`#noqa: secret` (no space after #) also suppresses."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"  #noqa: secret\n'
        )
        self.assertEqual(scan_diff(diff, [_aws_pattern()]), [])

    def test_noqa_other_codes_do_not_suppress(self):
        """`# noqa: E501` (different code) does NOT suppress secret findings."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"  # noqa: E501\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].pattern_name, "aws-access-key")


class TestSkipTestsFilter(unittest.TestCase):
    """`Pattern.skip_tests` opts a pattern out of test-file scanning."""

    def test_skip_tests_true_skips_test_file_path(self):
        """A skip_tests=True pattern emits no Finding in a test-file path."""
        diff = (
            "+++ b/plugins/xp-agents/tests/hooks/test_thing.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"\n'
        )
        self.assertEqual(scan_diff(diff, [_aws_pattern(skip_tests=True)]), [])

    def test_skip_tests_true_matches_in_non_test_file(self):
        """A skip_tests=True pattern still emits in a production-code path."""
        diff = (
            "+++ b/plugins/xp-agents/scripts/cfg.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"\n'
        )
        findings = scan_diff(diff, [_aws_pattern(skip_tests=True)])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].file_path, "plugins/xp-agents/scripts/cfg.py")

    def test_skip_tests_false_matches_in_test_file(self):
        """A skip_tests=False pattern emits in test-file paths too."""
        diff = (
            "+++ b/plugins/xp-agents/tests/hooks/test_thing.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"\n'
        )
        findings = scan_diff(diff, [_aws_pattern(skip_tests=False)])
        self.assertEqual(len(findings), 1)

    def test_mixed_skip_tests_patterns_in_one_call(self):
        """In a test file, only the skip_tests=False pattern fires; the
        skip_tests=True pattern is skipped — verifies the per-pattern filter
        doesn't short-circuit the whole pattern loop."""
        skip_pat = Pattern(
            name="skip-me-in-tests",
            regex=re.compile(r"AKIA[0-9A-Z]{16}"),
            skip_tests=True,
        )
        always_pat = Pattern(
            name="always-fire",
            regex=re.compile(r"AKIA[0-9A-Z]{16}"),
            skip_tests=False,
        )
        diff = (
            "+++ b/plugins/xp-agents/tests/hooks/test_thing.py\n"
            "@@ -0,0 +1,1 @@\n"
            '+key = "AKIA1234567890ABCDEF"\n'
        )
        findings = scan_diff(diff, [skip_pat, always_pat])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].pattern_name, "always-fire")


class TestStory001E2E(unittest.TestCase):
    """Story-001 acceptance criterion #4: planted secret + noqa-suppressed line."""

    def test_planted_secret_reported_noqa_line_not(self):
        """E2E: a diff with one planted secret and one noqa-suppressed line —
        exactly the planted line is reported, the noqa line is not."""
        diff = (
            "+++ b/scripts/cfg.py\n"
            "@@ -0,0 +1,2 @@\n"
            '+real_secret = "AKIA1111111111111111"\n'
            '+example_secret = "AKIA2222222222222222"  # noqa: secret\n'
        )
        findings = scan_diff(diff, [_aws_pattern()])
        self.assertEqual(len(findings), 1)
        self.assertIn("AKIA1111111111111111", findings[0].line_content)
        self.assertNotIn("AKIA2222222222222222", findings[0].line_content)


if __name__ == "__main__":
    unittest.main()
