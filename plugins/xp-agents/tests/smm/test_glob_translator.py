#!/usr/bin/env python3
"""Behavior pins for the shared glob → regex translator.

The translator was previously duplicated as triage._glob_to_regex
(`(?:.*/)?` for `**/`) and sister_tests._compile_source_pattern
(`(?:.+/)?`). Both forms have an outer `?` making the group optional,
so both already matched zero segments — the two forms only differ for
paths beginning with `/`, which never appear as project-relative inputs.
These tests pin the unified semantics so a future re-divergence
surfaces in CI rather than at acceptance time.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "smm"))

from glob_translator import glob_to_regex


def _matches(pattern: str, candidate: str) -> bool:
    return re.fullmatch(glob_to_regex(pattern), candidate) is not None


class TestStarStarSlashIsZeroOrMore(unittest.TestCase):
    """`**/X` matches X at depth 0 (root) AND any depth ≥ 1.

    Both former forms (`(?:.+/)?` and `(?:.*/)?`) already allowed zero
    segments via the outer `?`. The unified primitive uses `(?:.*/)?`;
    these tests pin the zero-segment case so a future regression that
    drops the outer `?` (e.g. `(?:.+/)+` or `.+/`) is caught here.
    """

    def test_root_level_match(self) -> None:
        self.assertTrue(_matches("**/*.py", "a.py"))
        self.assertTrue(_matches("**/*.js", "x.js"))

    def test_nested_match(self) -> None:
        self.assertTrue(_matches("**/*.py", "src/a.py"))
        self.assertTrue(_matches("**/*.py", "src/pkg/sub/a.py"))

    def test_brace_in_segment_outside_translator_scope(self) -> None:
        # Brace expansion happens BEFORE the translator; this just confirms
        # the translator doesn't accidentally swallow `{` as a metachar.
        self.assertFalse(_matches("**/*.{js,ts}", "a.js"))


class TestTrailingStarStar(unittest.TestCase):
    """`prefix/**` matches `prefix` AND `prefix/anything-deep`."""

    def test_bare_prefix(self) -> None:
        self.assertTrue(_matches("src/**", "src"))

    def test_one_level(self) -> None:
        self.assertTrue(_matches("src/**", "src/a.py"))

    def test_deep(self) -> None:
        self.assertTrue(_matches("src/**", "src/a/b/c.py"))

    def test_sibling_does_not_match(self) -> None:
        self.assertFalse(_matches("src/**", "tests/a.py"))


class TestStarSingleSegment(unittest.TestCase):
    def test_star_stops_at_slash(self) -> None:
        self.assertTrue(_matches("src/*.py", "src/a.py"))
        self.assertFalse(_matches("src/*.py", "src/sub/a.py"))


class TestQuestionMark(unittest.TestCase):
    def test_question_mark_one_char_no_slash(self) -> None:
        self.assertTrue(_matches("a?c", "abc"))
        self.assertFalse(_matches("a?c", "a/c"))
        self.assertFalse(_matches("a?c", "abbc"))


class TestBrackets(unittest.TestCase):
    def test_bracket_class_passes_through(self) -> None:
        self.assertTrue(_matches("file[abc].py", "filea.py"))
        self.assertTrue(_matches("file[abc].py", "fileb.py"))
        self.assertFalse(_matches("file[abc].py", "filed.py"))

    def test_malformed_bracket_escapes_to_literal(self) -> None:
        # No closing `]` → `[` treated as literal `\[`; downstream chars
        # are still translated normally. `file[abc.py` would never match
        # `file[abc.py` after fullmatch because translator continues from
        # i+1 — the test pins the documented fall-back behavior.
        rx = glob_to_regex("file[abc.py")
        self.assertEqual(rx, r"file\[abc\.py")


class TestLiteralEscaping(unittest.TestCase):
    def test_dot_is_escaped(self) -> None:
        # Trivial-looking but load-bearing: `a.py` MUST NOT match `axpy`.
        self.assertFalse(_matches("a.py", "axpy"))
        self.assertTrue(_matches("a.py", "a.py"))


if __name__ == "__main__":
    unittest.main()
