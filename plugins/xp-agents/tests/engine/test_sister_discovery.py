#!/usr/bin/env python3
"""Generic discover_sister_tests edge-case suite for sister_tests.

Split out of tests/hooks/test_sister_tests.py: that file keeps the compiler /
pure-function mechanics plus the shared ``_DiscoveryTestCase`` base; this file
holds the layout-agnostic discovery edge cases (absolute-path guard, custom
layouts, no-match behavior). The shared base and ``_touch`` helper are imported
from test_sister_tests so exactly one definition exists.
"""

import shutil
import sys
import unittest
from pathlib import Path

# test_sister_tests lives in tests/hooks/, which conftest does not put on
# sys.path; insert it so the shared base imports regardless of collection order.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from sister_tests import (  # pyright: ignore[reportMissingImports]
    TestLayout,
    TestLayoutRule,
    discover_sister_tests,
)
from test_sister_tests import (  # pyright: ignore[reportMissingImports]
    _DiscoveryTestCase,
    _touch,
)


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

    def test_source_excludes_honors_brace_alternation(self):
        # source_excludes must brace-expand like source_pattern. Without
        # symmetry, a customer override `source_excludes=['test/{foo,bar}/**']`
        # would silently match only the literal pattern and let real
        # test/foo/... files through. Mirrors _match_any semantics.
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="{dir}/test_{stem}.py",
                    source_excludes=("test/{foo,bar}/**",),
                ),
            ),
        )
        _touch(self.root, "test/foo/test_x.py")
        _touch(self.root, "test/bar/test_y.py")
        # Both source paths must be excluded — same as if the rule listed
        # 'test/foo/**' and 'test/bar/**' separately.
        self.assertEqual(discover_sister_tests("test/foo/x.py", layout, self.root), [])
        self.assertEqual(discover_sister_tests("test/bar/y.py", layout, self.root), [])

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

    def test_escaping_dotdot_resolved_path_is_filtered(self):
        # Mirrors csharp_xunit R2 with a root-level source: {dir}/../Tests/...
        # resolves to '../Tests/FooTests.cs' which escapes project_root.
        # discover_sister_tests must drop these instead of returning lexical
        # '../...' paths that violate the project-relative contract.
        sibling = self.root.parent / "sister_tests_escape_target"
        sibling.mkdir(parents=True, exist_ok=True)
        try:
            (sibling / "Tests").mkdir(exist_ok=True)
            (sibling / "Tests" / "FooTests.cs").write_text("")
            # Rename the sibling to land at <root>/../Tests via the rule.
            tests_outside = self.root.parent / "Tests"
            tests_outside.mkdir(exist_ok=True)
            (tests_outside / "FooTests.cs").write_text("")
            layout = TestLayout(
                convention="custom",
                rules=(
                    TestLayoutRule(
                        source_pattern="**/*.cs",
                        stem_extractor="basename_no_ext",
                        test_glob="{dir}/../Tests/{stem}Tests.cs",
                    ),
                ),
            )
            self.assertEqual(
                discover_sister_tests("Foo.cs", layout, self.root),
                [],
            )
        finally:
            shutil.rmtree(sibling, ignore_errors=True)
            shutil.rmtree(self.root.parent / "Tests", ignore_errors=True)

    def test_absolute_resolved_path_is_filtered(self):
        # A rule whose test_glob is absolute must be skipped — discover_sister_tests
        # promises project-relative results.
        layout = TestLayout(
            convention="custom",
            rules=(
                TestLayoutRule(
                    source_pattern="**/*.py",
                    stem_extractor="basename_no_ext",
                    test_glob="/abs/tests/test_{stem}.py",
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


if __name__ == "__main__":
    unittest.main()
