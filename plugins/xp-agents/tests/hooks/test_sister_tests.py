#!/usr/bin/env python3
"""Tests for the sister-test discovery primitive."""

import sys
import unittest
from pathlib import Path

# The skill's scripts/ dir isn't on conftest's sys.path; shim it in.
_SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "skills" / "xp-sprint-start" / "scripts"
)
sys.path.insert(0, str(_SKILL_SCRIPTS))

from sister_tests import (  # noqa: E402
    _compile_source_pattern,
    _expand_braces,
    _match_any,
)


class TestBraceExpansion(unittest.TestCase):
    def test_no_braces_returns_singleton(self):
        self.assertEqual(_expand_braces("foo.py"), ["foo.py"])

    def test_empty_string_returns_singleton_empty(self):
        self.assertEqual(_expand_braces(""), [""])

    def test_single_group_expands_in_order(self):
        self.assertEqual(
            _expand_braces("foo.{js,ts}"),
            ["foo.js", "foo.ts"],
        )

    def test_single_group_three_options(self):
        self.assertEqual(
            _expand_braces("a.{js,jsx,ts,tsx}"),
            ["a.js", "a.jsx", "a.ts", "a.tsx"],
        )

    def test_group_with_prefix_and_suffix(self):
        self.assertEqual(
            _expand_braces("pre/{x,y}/post.rb"),
            ["pre/x/post.rb", "pre/y/post.rb"],
        )

    def test_two_groups_cartesian_product(self):
        self.assertEqual(
            _expand_braces("{a,b}.{x,y}"),
            ["a.x", "a.y", "b.x", "b.y"],
        )

    def test_unclosed_brace_passes_through(self):
        self.assertEqual(_expand_braces("foo.{js"), ["foo.{js"])

    def test_no_open_brace_passes_through(self):
        self.assertEqual(_expand_braces("foo}.js"), ["foo}.js"])

    def test_single_option_in_group(self):
        self.assertEqual(_expand_braces("foo.{js}"), ["foo.js"])


class TestSourcePatternCompiler(unittest.TestCase):
    """Mid-pattern ** must work on Py 3.11/3.12 (PurePosixPath.match doesn't).

    The compiler turns a shell-glob into a re.Pattern with cross-segment
    semantics: ``**/x`` matches ``x``, ``a/x``, ``a/b/x`` (zero-or-more
    segments). Single ``*`` matches within one segment. ``?`` matches a
    single non-slash char. ``[seq]`` passes through to regex character class.
    """

    def test_star_matches_single_segment(self):
        pat = _compile_source_pattern("*.py")
        self.assertIsNotNone(pat.fullmatch("foo.py"))
        # * does NOT cross a slash
        self.assertIsNone(pat.fullmatch("a/foo.py"))

    def test_double_star_slash_matches_zero_or_more_segments(self):
        pat = _compile_source_pattern("**/*.py")
        self.assertIsNotNone(pat.fullmatch("foo.py"))
        self.assertIsNotNone(pat.fullmatch("a/foo.py"))
        self.assertIsNotNone(pat.fullmatch("a/b/c/foo.py"))

    def test_mid_pattern_double_star_ruby_rspec(self):
        # The bug PurePosixPath.match misses on 3.11/3.12.
        pat = _compile_source_pattern("lib/**/*.rb")
        self.assertIsNotNone(pat.fullmatch("lib/foo.rb"))
        self.assertIsNotNone(pat.fullmatch("lib/foo/bar.rb"))
        self.assertIsNotNone(pat.fullmatch("lib/a/b/c.rb"))
        self.assertIsNone(pat.fullmatch("other/foo.rb"))

    def test_mid_pattern_double_star_java_junit(self):
        pat = _compile_source_pattern("src/main/java/**/*.java")
        self.assertIsNotNone(pat.fullmatch("src/main/java/com/x/Foo.java"))
        self.assertIsNotNone(pat.fullmatch("src/main/java/Foo.java"))
        self.assertIsNone(pat.fullmatch("src/test/java/Foo.java"))

    def test_mid_pattern_double_star_php_phpunit(self):
        pat = _compile_source_pattern("src/**/*.php")
        self.assertIsNotNone(pat.fullmatch("src/Foo.php"))
        self.assertIsNotNone(pat.fullmatch("src/a/b/Bar.php"))

    def test_mid_pattern_double_star_elixir_exunit(self):
        pat = _compile_source_pattern("lib/**/*.ex")
        self.assertIsNotNone(pat.fullmatch("lib/foo.ex"))
        self.assertIsNotNone(pat.fullmatch("lib/a/b/foo.ex"))

    def test_mid_pattern_double_star_swift_xctest(self):
        pat = _compile_source_pattern("Sources/**/*.swift")
        self.assertIsNotNone(pat.fullmatch("Sources/A/B/Foo.swift"))
        self.assertIsNotNone(pat.fullmatch("Sources/Foo.swift"))

    def test_question_mark_single_non_slash_char(self):
        pat = _compile_source_pattern("foo?.py")
        self.assertIsNotNone(pat.fullmatch("foo1.py"))
        self.assertIsNone(pat.fullmatch("foo.py"))
        self.assertIsNone(pat.fullmatch("foo/x.py"))

    def test_charclass_passthrough(self):
        pat = _compile_source_pattern("foo[12].py")
        self.assertIsNotNone(pat.fullmatch("foo1.py"))
        self.assertIsNotNone(pat.fullmatch("foo2.py"))
        self.assertIsNone(pat.fullmatch("foo3.py"))

    def test_literal_dot_is_escaped(self):
        # '.' in glob means literal dot, not regex "any char".
        pat = _compile_source_pattern("foo.py")
        self.assertIsNotNone(pat.fullmatch("foo.py"))
        self.assertIsNone(pat.fullmatch("fooXpy"))


class TestMatchAny(unittest.TestCase):
    """_match_any brace-expands the pattern then tests each branch."""

    def test_brace_expanded_pattern_matches_any_branch(self):
        self.assertTrue(_match_any("foo.js", "*.{js,ts}"))
        self.assertTrue(_match_any("foo.ts", "*.{js,ts}"))
        self.assertFalse(_match_any("foo.py", "*.{js,ts}"))

    def test_plain_pattern_no_expansion_needed(self):
        self.assertTrue(_match_any("a/b/c.go", "**/*.go"))


if __name__ == "__main__":
    unittest.main()
