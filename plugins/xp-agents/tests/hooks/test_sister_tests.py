#!/usr/bin/env python3
"""Tests for the sister-test discovery primitive."""

import shutil
import tempfile
import unittest
from pathlib import Path

from sister_tests import (  # pyright: ignore[reportMissingImports]
    STEM_EXTRACTORS,
    TestLayoutRule,
    _compile_source_pattern,
    _expand_braces,
    _literal_prefix,
    _match_any,
    _resolve_test_glob,
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


class TestLiteralPrefix(unittest.TestCase):
    """_literal_prefix slices a glob at the dir-segment before the first metachar."""

    def test_no_metachars_returns_full_pattern(self):
        # No glob metachar -> the whole thing is literal.
        self.assertEqual(_literal_prefix("docs/intro.md"), "docs/intro.md")

    def test_double_star_at_root(self):
        self.assertEqual(_literal_prefix("**/*.py"), "")

    def test_dir_then_double_star(self):
        self.assertEqual(_literal_prefix("lib/**/*.rb"), "lib/")

    def test_nested_dirs_then_double_star(self):
        self.assertEqual(
            _literal_prefix("src/main/java/**/*.java"),
            "src/main/java/",
        )

    def test_single_star_in_basename_cuts_to_dir(self):
        # 'src/bin/*.rs' -> 'src/bin/'
        self.assertEqual(_literal_prefix("src/bin/*.rs"), "src/bin/")

    def test_question_mark_cuts_to_dir(self):
        self.assertEqual(_literal_prefix("a/b/foo?.txt"), "a/b/")

    def test_charclass_cuts_to_dir(self):
        self.assertEqual(_literal_prefix("a/b/foo[12].txt"), "a/b/")

    def test_brace_in_prefix_cuts_to_dir(self):
        # Brace-alternation is a glob metachar — a brace-prefixed segment
        # must be treated as non-literal so {mirror} substitution uses the
        # correct strip prefix. Without this, source_pattern='src/{a,b}/**/*.py'
        # returned literal prefix 'src/{a,b}/' and downstream mirror calc
        # failed to strip 'src/' from the source's parent dir.
        self.assertEqual(_literal_prefix("src/{a,b}/**/*.py"), "src/")
        self.assertEqual(_literal_prefix("lib/{x,y,z}/*.rb"), "lib/")
        self.assertEqual(_literal_prefix("{foo,bar}/*.py"), "")


class TestResolveTestGlob(unittest.TestCase):
    """_resolve_test_glob substitutes {stem}, {dir}, {mirror} then brace-expands."""

    def _make_rule(self, source_pattern, test_glob):
        return TestLayoutRule(
            source_pattern=source_pattern,
            stem_extractor="basename_no_ext",
            test_glob=test_glob,
        )

    def test_stem_substitution(self):
        from pathlib import PurePosixPath

        rule = self._make_rule("**/*.go", "{dir}/{stem}_test.go")
        out = _resolve_test_glob(rule, "foo", PurePosixPath("pkg/foo.go"))
        self.assertEqual(out, ["pkg/foo_test.go"])

    def test_brace_expansion_after_substitution(self):
        from pathlib import PurePosixPath

        rule = self._make_rule(
            "**/*.{js,ts}",
            "{dir}/{stem}.test.{js,jsx,ts,tsx}",
        )
        out = _resolve_test_glob(rule, "foo", PurePosixPath("src/foo.js"))
        self.assertEqual(
            out,
            [
                "src/foo.test.js",
                "src/foo.test.jsx",
                "src/foo.test.ts",
                "src/foo.test.tsx",
            ],
        )

    def test_mirror_strips_literal_prefix(self):
        from pathlib import PurePosixPath

        # ruby_rspec R2 shape: prefix "lib/" stripped from src.parent.
        rule = self._make_rule("lib/**/*.rb", "spec/{mirror}/{stem}_spec.rb")
        out = _resolve_test_glob(rule, "bar", PurePosixPath("lib/foo/bar.rb"))
        self.assertEqual(out, ["spec/foo/bar_spec.rb"])

    def test_mirror_collapses_when_source_directly_under_prefix(self):
        from pathlib import PurePosixPath

        # Source 'lib/bar.rb' → mirror='' → 'spec//bar_spec.rb' → 'spec/bar_spec.rb'.
        rule = self._make_rule("lib/**/*.rb", "spec/{mirror}/{stem}_spec.rb")
        out = _resolve_test_glob(rule, "bar", PurePosixPath("lib/bar.rb"))
        self.assertEqual(out, ["spec/bar_spec.rb"])

    def test_mirror_with_nested_dirs(self):
        from pathlib import PurePosixPath

        # java_junit: prefix 'src/main/java/' stripped.
        rule = self._make_rule(
            "src/main/java/**/*.java",
            "src/test/java/{mirror}/{stem}Test.java",
        )
        out = _resolve_test_glob(
            rule, "Foo", PurePosixPath("src/main/java/com/acme/Foo.java")
        )
        self.assertEqual(out, ["src/test/java/com/acme/FooTest.java"])

    def test_dir_substitution_no_mirror(self):
        from pathlib import PurePosixPath

        rule = self._make_rule("**/*.py", "{dir}/tests/test_{stem}.py")
        out = _resolve_test_glob(rule, "foo", PurePosixPath("pkg/foo.py"))
        self.assertEqual(out, ["pkg/tests/test_foo.py"])


def _make_tmp_project() -> Path:
    """Create a temp dir and register it for cleanup at test end."""
    return Path(tempfile.mkdtemp(prefix="sister_tests_"))


def _touch(root: Path, rel: str) -> None:
    """Create an empty file at ``root/rel``, including parent dirs."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("")


class _DiscoveryTestCase(unittest.TestCase):
    """Base: gives each test a temp project_root with auto-cleanup."""

    def setUp(self):
        self.root = _make_tmp_project()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)


class TestExtractors(unittest.TestCase):
    def test_basename_no_ext_registered(self):
        self.assertIn("basename_no_ext", STEM_EXTRACTORS)

    def test_basename_no_ext_strips_extension(self):
        fn = STEM_EXTRACTORS["basename_no_ext"]
        self.assertEqual(fn("pkg/foo.go"), "foo")
        self.assertEqual(fn("a/b/c/bar.py"), "bar")

    def test_basename_no_ext_returns_none_for_extensionless(self):
        fn = STEM_EXTRACTORS["basename_no_ext"]
        # An empty stem (no leading basename) returns None per design — guard
        # for things like "/" or "" that shouldn't produce a stemless test glob.
        self.assertIsNone(fn(""))

    def test_skill_dir_xp_strip_not_registered(self):
        # Per plan-review concern #5 (YAGNI): defer until consumer exists.
        self.assertNotIn("skill_dir_xp_strip", STEM_EXTRACTORS)
        self.assertNotIn("_skill_dir_xp_strip", STEM_EXTRACTORS)
