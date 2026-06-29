#!/usr/bin/env python3
"""Tests for the sister-test discovery primitive."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# The skill's scripts/ dir isn't on conftest's sys.path; shim it in.
_SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "skills" / "xp-sprint-start" / "scripts"
)
sys.path.insert(0, str(_SKILL_SCRIPTS))

from sister_tests import (  # noqa: E402
    BUILTIN_LAYOUTS,
    STEM_EXTRACTORS,
    TestLayout,
    TestLayoutRule,
    _compile_source_pattern,
    _expand_braces,
    _literal_prefix,
    _match_any,
    _resolve_test_glob,
    discover_sister_tests,
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


# Need TestLayoutRule for _resolve_test_glob tests. Import lazily inside the
# class to keep this commit's red phase honest — _resolve_test_glob is what's
# being added now; TestLayoutRule comes in the next commit. For now we pass a
# tiny shim object via a SimpleNamespace duck-type.
class TestResolveTestGlob(unittest.TestCase):
    """_resolve_test_glob substitutes {stem}, {dir}, {mirror} then brace-expands."""

    def _make_rule(self, source_pattern, test_glob):
        from types import SimpleNamespace

        return SimpleNamespace(source_pattern=source_pattern, test_glob=test_glob)

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


class TestDiscoveryEdgeCases(_DiscoveryTestCase):
    def test_absolute_source_path_raises(self):
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="tests/test_{stem}.py",
                ),
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            discover_sister_tests("/abs/foo.py", layout, self.root)
        self.assertIn("project-relative", str(ctx.exception))

    def test_unknown_extractor_raises_naming_it(self):
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="not_a_real_extractor",
                    test_glob="tests/test_{stem}.py",
                ),
            ),
        )
        with self.assertRaises(ValueError) as ctx:
            discover_sister_tests("pkg/foo.py", layout, self.root)
        self.assertIn("not_a_real_extractor", str(ctx.exception))

    def test_skip_basename_filters_source(self):
        _touch(self.root, "tests/test___init__.py")
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="tests/test_{stem}.py",
                    skip_basenames=("__init__.py",),
                ),
            ),
        )
        self.assertEqual(
            discover_sister_tests("pkg/__init__.py", layout, self.root), []
        )

    def test_skip_suffix_filters_source(self):
        # Source 'pkg/foo_test.go' must be skipped — it IS a test file.
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.go",
                    stem_extractor="basename_no_ext",
                    test_glob="{dir}/{stem}_test.go",
                    skip_suffixes=("_test.go",),
                ),
            ),
        )
        self.assertEqual(
            discover_sister_tests("pkg/foo_test.go", layout, self.root), []
        )

    def test_source_excludes_filters_source(self):
        # Mirrors csharp_xunit obj/bin exclusion shape.
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.cs",
                    stem_extractor="basename_no_ext",
                    test_glob="{dir}/{stem}Tests.cs",
                    source_excludes=("obj/**", "bin/**"),
                ),
            ),
        )
        # File on disk would otherwise match — but the source itself is excluded.
        _touch(self.root, "obj/FooTests.cs")
        self.assertEqual(discover_sister_tests("obj/Foo.cs", layout, self.root), [])

    def test_returns_sorted_deduped_posix_strings(self):
        # Two rules both produce the same sister file -> single result.
        _touch(self.root, "tests/test_foo.py")
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="tests/test_{stem}.py",
                ),
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="tests/test_{stem}.py",
                ),
            ),
        )
        self.assertEqual(
            discover_sister_tests("pkg/foo.py", layout, self.root),
            ["tests/test_foo.py"],
        )

    def test_overrides_concatenate_with_rules(self):
        _touch(self.root, "tests/test_foo.py")
        _touch(self.root, "spec/foo_spec.py")
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="tests/test_{stem}.py",
                ),
            ),
            overrides=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="spec/{stem}_spec.py",
                ),
            ),
        )
        self.assertEqual(
            discover_sister_tests("pkg/foo.py", layout, self.root),
            ["spec/foo_spec.py", "tests/test_foo.py"],
        )

    def test_no_matching_rule_returns_empty(self):
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.go",
                    stem_extractor="basename_no_ext",
                    test_glob="{dir}/{stem}_test.go",
                ),
            ),
        )
        self.assertEqual(discover_sister_tests("pkg/foo.py", layout, self.root), [])

    def test_rule_matches_but_no_test_file_on_disk_returns_empty(self):
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="tests/test_{stem}.py",
                ),
            ),
        )
        # No test file written -> empty result, no crash.
        self.assertEqual(discover_sister_tests("pkg/foo.py", layout, self.root), [])


class TestBuiltinLayoutsScaffold(unittest.TestCase):
    """The BUILTIN_LAYOUTS dict exists; per-language entries land in later commits."""

    def test_builtin_layouts_is_a_dict(self):
        self.assertIsInstance(BUILTIN_LAYOUTS, dict)


if __name__ == "__main__":
    unittest.main()
