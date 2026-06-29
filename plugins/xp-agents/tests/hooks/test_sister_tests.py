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

from sister_tests import _expand_braces  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
